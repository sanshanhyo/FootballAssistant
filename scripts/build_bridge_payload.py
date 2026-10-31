"""Build a hash-pinned, source/license-complete candidate. No game input or execution."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'modules/game-bridge/packaging/payload-sources.json'
ALLOWED_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'codeload.github.com', 'builds.dotnet.microsoft.com'}

def sha(file, algorithm='sha256'):
    with file.open('rb') as stream: return hashlib.file_digest(stream, algorithm).hexdigest()

def trusted_url(url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password or parsed.port: raise ValueError('Untrusted payload source URL')

class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download(url, destination, expected, algorithm):
    trusted_url(url)
    if destination.is_file() and sha(destination,algorithm)==expected: return
    temporary=destination.with_suffix(destination.suffix+'.part')
    try:
        with urllib.request.build_opener(Redirects()).open(url,timeout=90) as src, temporary.open('wb') as out:
            total=0
            while block:=src.read(1024*1024):
                total+=len(block)
                if total>256*1024*1024:raise ValueError('Payload archive exceeds size budget')
                out.write(block)
        if sha(temporary,algorithm)!=expected:raise ValueError('Official payload digest mismatch')
        temporary.replace(destination)
    finally:temporary.unlink(missing_ok=True)

def put_bytes(root, relative, data, mode=0o644):
    path=Path(relative)
    if path.is_absolute() or '..' in path.parts: raise ValueError('Archive path traversal')
    destination=root/path;destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb') as out:out.write(data)
    destination.chmod(mode & 0o777)

def build(plugin, output, cache):
    if output.exists():raise ValueError('Candidate output already exists; use a fresh build directory')
    if plugin.is_symlink() or not plugin.is_file() or plugin.read_bytes()[:2]!=b'MZ':raise ValueError('Expected compiled managed bridge DLL')
    lock=json.loads(LOCK.read_text());cache.mkdir(parents=True,exist_ok=True)
    doorstop=cache/'doorstop.zip';source=cache/'doorstop-source.tar.gz';runtime=cache/'dotnet-runtime.tar.gz'
    download(lock['doorstop']['url'],doorstop,lock['doorstop']['sha256'],'sha256')
    download(lock['doorstop']['sourceUrl'],source,lock['doorstop']['sourceSha256'],'sha256')
    download(lock['runtime']['url'],runtime,lock['runtime']['sha512'],'sha512')
    output.mkdir(parents=True)
    with zipfile.ZipFile(doorstop) as z:
        library=z.read('universal/libdoorstop.dylib')
        if hashlib.sha256(library).hexdigest()!=lock['doorstop']['librarySha256']:raise ValueError('Reviewed Doorstop library differs')
        put_bytes(output,'libdoorstop.dylib',library,0o755)
        put_bytes(output,'licenses/Doorstop-LICENSE',z.read('LICENSE'))
    put_bytes(output,'sources/UnityDoorstop-'+lock['doorstop']['sourceCommit']+'.tar.gz',source.read_bytes())
    prefix='shared/Microsoft.NETCore.App/'+lock['runtime']['version']+'/'
    runtime_count=0
    with tarfile.open(runtime,'r:gz') as archive:
        for member in archive:
            name=member.name.removeprefix('./')
            if name.startswith(prefix) and member.isfile():
                relative=name[len(prefix):]
                if not relative or '/' in relative:raise ValueError('Unexpected nested runtime entry')
                put_bytes(output,'runtime/'+relative,archive.extractfile(member).read(),member.mode);runtime_count+=1
            elif name in {'LICENSE.txt','ThirdPartyNotices.txt'} and member.isfile():
                put_bytes(output,'licenses/dotnet-'+name,archive.extractfile(member).read())
    if runtime_count<100 or not (output/'runtime/libcoreclr.dylib').is_file():raise ValueError('Incomplete runtime archive')
    for required in ['licenses/Doorstop-LICENSE','licenses/dotnet-LICENSE.txt','licenses/dotnet-ThirdPartyNotices.txt']:
        if not (output/required).is_file():raise ValueError('Required redistributable notice missing')
    put_bytes(output,'FootballAssistant.GameBridge.dll',plugin.read_bytes())
    put_bytes(output,'licenses/FootballAssistant-LICENSE',(ROOT/'LICENSE').read_bytes())
    # Include corresponding source for our GPL bridge, not only upstream loader source.
    source_bytes = io.BytesIO()
    with tarfile.open(fileobj=source_bytes, mode='w:gz') as own_source:
        source_files = sorted((ROOT/'modules/game-bridge/src').glob('*.cs')) + [ROOT/'modules/game-bridge/FootballAssistant.DirectBridge.csproj', ROOT/'LICENSE']
        for file in source_files:
            if file.is_symlink() or not file.is_file(): raise ValueError('Unsafe bridge source file')
            own_source.add(file, arcname=str(file.relative_to(ROOT)), recursive=False)
    put_bytes(output,'sources/FootballAssistant-GameBridge-source.tar.gz',source_bytes.getvalue())
    put_bytes(output,'source-provenance.json',(json.dumps(lock,indent=2)+'\n').encode())
    files={str(file.relative_to(output)):sha(file) for file in sorted(output.rglob('*')) if file.is_file()}
    manifest={'schema':1,'target':'darwin-arm64','entryMode':'direct','reviewed':False,'validation':'pending_isolated_game_acceptance','files':files,'sources':lock,'runtimeFiles':runtime_count}
    put_bytes(output,'payload.json',(json.dumps(manifest,indent=2)+'\n').encode())
    size=sum(file.stat().st_size for file in output.rglob('*') if file.is_file())
    report={'target':'darwin-arm64','reviewed':False,'fileCount':len(files)+1,'unpackedBytes':size,'runtimeFiles':runtime_count,'gameFilesIncluded':False}
    print(json.dumps(report));return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'build/bridge-macos-arm64-candidate')
    parser.add_argument('--cache',type=Path,default=ROOT/'build/bridge-source-cache')
    args=parser.parse_args();build(args.plugin,args.output,args.cache)
