"""Build a pinned BepInEx/MatchReader payload; never reads or launches a game."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.parse
import urllib.request
import zipfile
from reassemble_windows_match_archive import reassemble

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'modules/game-bridge/packaging/windows-match-sources.json'
LICENSE_DIRS = [ROOT / 'modules/game-bridge/packaging' / n for n in ['windows-match-licenses', 'windows-match-native-licenses']]
ALLOWED_HOSTS = {'builds.bepinex.dev', 'github.com', 'release-assets.githubusercontent.com', 'codeload.github.com'}
PLUGIN = 'BepInEx/plugins/FootballAssistant/FootballAssistant.MatchReader.dll'

def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def trusted(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != 'https' or p.hostname not in ALLOWED_HOSTS or p.username or p.password or p.port:
        raise ValueError('Untrusted component source')

class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download(url, destination, expected):
    if not re.fullmatch('[a-f0-9]{64}', expected): raise ValueError('Missing pinned source hash')
    trusted(url); destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and not destination.is_symlink() and sha(destination) == expected: return
    temp = destination.with_suffix(destination.suffix + '.part')
    try:
        with urllib.request.build_opener(Redirects()).open(url, timeout=120) as src, temp.open('wb') as out:
            total = 0
            while block := src.read(1024 * 1024):
                total += len(block)
                if total > 256 * 1024 * 1024: raise ValueError('Source exceeds size budget')
                out.write(block)
        if sha(temp) != expected: raise ValueError('Source SHA-256 mismatch')
        temp.replace(destination)
    finally: temp.unlink(missing_ok=True)

def relative(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or any(x in {'', '.', '..'} for x in name.split('/')) or '\\' in name or ':' in name:
        raise ValueError('Unsafe component path')
    return p

def deployment_path(name):
    return name in {'winhttp.dll', '.doorstop_version', 'doorstop_config.ini'} or name.startswith(('dotnet/', 'BepInEx/core/')) or name == PLUGIN

def extract(pin, archive, destination):
    if destination.exists(): raise ValueError('Use a fresh build staging directory')
    destination.mkdir(parents=True)
    seen = set(); total = 0
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            name = entry.filename.rstrip('/'); relative(name)
            if name.lower() in seen: raise ValueError('Duplicate archive member')
            seen.add(name.lower())
            if stat.S_ISLNK(entry.external_attr >> 16): raise ValueError('Archive link forbidden')
            if entry.is_dir(): continue
            if name == 'changelog.txt': continue
            if not deployment_path(name): raise ValueError('Unexpected official loader file')
            total += entry.file_size
            if total > 150 * 1024 * 1024: raise ValueError('Loader exceeds size budget')
            target = destination / relative(name); target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as f: f.write(z.read(entry))
    for name in pin['requiredFiles']:
        if not (destination / name).is_file(): raise ValueError(f'Missing loader component: {name}')

def inventory(root):
    result = {}; sizes = {}
    for file in sorted(root.rglob('*')):
        if file.is_symlink(): raise ValueError('Payload symlink forbidden')
        if file.is_file() and file != root / 'manifest.json':
            name = file.relative_to(root).as_posix(); result[name] = sha(file); sizes[name] = file.stat().st_size
    return result, sizes

def prepare(cache, staging):
    pin = json.loads(PIN.read_text())
    # Offline official dependency: never fall back to the upstream download service.
    archive = reassemble(ROOT / relative(pin['loader']['offlineManifest']), cache / 'bepinex.zip', pin['loader']['sourceSha256'])
    extract(pin, archive, staging)

def assemble(cache, staging, plugin, output):
    pin = json.loads(PIN.read_text())
    if output.exists(): raise ValueError('Use a fresh payload output directory')
    if plugin.is_symlink() or not plugin.is_file() or plugin.read_bytes()[:2] != b'MZ': raise ValueError('Compiled MatchReader DLL required')
    # Re-create only from the fixed official archive; no mutable staging or user directory sweep.
    prepare(cache, output / 'payload')
    payload = output / 'payload'; notices = output / 'licenses'; notices.mkdir()
    sources = output / 'sources'; sources.mkdir()
    covered = {}; components = []
    for directory in LICENSE_DIRS:
        spec = json.loads((directory / 'components.json').read_text())
        for name, digest in spec['licenseHashes'].items():
            relative(name); file = directory / name
            if file.is_symlink() or not file.is_file() or sha(file) != digest: raise ValueError('License missing or changed')
        for component in spec['components']:
            cid = component['id']
            if not re.fullmatch('[A-Za-z0-9._-]+', cid): raise ValueError('Unsafe component id')
            for name in component['files']:
                relative(name)
                file = payload / name
                if not file.is_file() or sha(file) != component['fileHashes'][name]: raise ValueError(f'Component binary mismatch: {cid}/{name}')
                covered[name] = cid
            for name in component['licenseFiles']:
                if name not in spec['licenseHashes']: raise ValueError('Unpinned license')
                dest = notices / cid / relative(name); dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(directory / name, dest)
            if component.get('sourceArchiveRequired'):
                source = component['source']; dest = sources / (cid + '.tar.gz')
                download(source['url'], cache / (cid + '.tar.gz'), source['sha256'])
                excluded = set(source.get('excludeFiles', []))
                found = set()
                with tarfile.open(cache / (cid + '.tar.gz'), 'r:gz') as original, tarfile.open(dest, 'w:gz') as clean:
                    for member in original:
                        relative(member.name.rstrip('/'))
                        if member.name in excluded:
                            found.add(member.name); continue
                        if member.issym() or member.islnk(): raise ValueError('Source archive link requires review')
                        if member.isfile() and member.name.lower().endswith(('.dll', '.exe')): raise ValueError('Unreviewed source archive binary')
                        if member.isfile(): clean.addfile(member, original.extractfile(member))
                        elif member.isdir(): clean.addfile(member)
                        else: raise ValueError('Unsupported source archive entry')
                if found != excluded: raise ValueError('Source exclusion list differs from pinned archive')
            components.append(component)
    unknown = [p.relative_to(payload).as_posix() for p in payload.rglob('*.dll') if p.relative_to(payload).as_posix() not in covered]
    if unknown: raise ValueError('Unlicensed/unattributed DLLs: ' + ', '.join(unknown))
    target = payload / PLUGIN; target.parent.mkdir(parents=True); shutil.copyfile(plugin, target)
    shutil.copyfile(ROOT / 'LICENSE', notices / 'FootballAssistant-LICENSE.txt')
    shutil.copyfile(ROOT / 'modules/game-bridge/match-reader/vendor/LICENSE', notices / 'FMMatchLens-LICENSE.txt')
    with tarfile.open(sources / 'FootballAssistant-MatchReader-source.tar.gz', 'w:gz') as archive:
        for file in sorted((ROOT / 'modules/game-bridge/match-reader').rglob('*')):
            if file.is_file() and not file.is_symlink() and not any(x in {'bin', 'obj'} for x in file.parts) and file.suffix in {'.cs', '.csproj'}:
                archive.add(file, arcname=file.relative_to(ROOT).as_posix(), recursive=False)
        for file in [ROOT / 'LICENSE', ROOT / 'modules/game-bridge/match-reader/vendor/LICENSE']:
            archive.add(file, arcname=file.relative_to(ROOT).as_posix(), recursive=False)
    (output / 'source-provenance.json').write_text(json.dumps({'loader': pin['loader'], 'components': components, 'runtimePolicy': pin['runtimePolicy']}, indent=2) + '\n')
    hashes, sizes = inventory(output)
    manifest = {'schema': 1, 'target': 'win32-x64', 'producerId': 'io.footballassistant.matchreader',
        'protocol': 'fa-match-snapshot/0.1', 'loader': pin['loader'], 'files': hashes, 'fileSizes': sizes,
        'gamePluginSha256': pin['gamePluginSha256'], 'buildCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'deploymentPaths': sorted(p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()),
        'gameFilesIncluded': False, 'interopIncluded': False, 'firstRunInteropGenerationRequired': True,
        'realGameAcceptance': 'pending', 'runtimePolicy': pin['runtimePolicy'],
        'firstRunUnityLibraries': 'no-unstrip: generate interop from local game inputs; no Unity library download or bundled game assemblies'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify(output)

def verify(output):
    manifest = json.loads((output / 'manifest.json').read_text())
    hashes, sizes = inventory(output)
    if manifest['files'] != hashes or manifest['fileSizes'] != sizes: raise ValueError('Packaged payload hash/size mismatch')
    if manifest['target'] != 'win32-x64' or manifest['producerId'] != 'io.footballassistant.matchreader': raise ValueError('Wrong payload identity')
    paths = manifest['deploymentPaths']
    if not paths or len(paths) != len(set(paths)) or PLUGIN not in paths: raise ValueError('Incomplete deployment inventory')
    pin = json.loads(PIN.read_text())
    if manifest.get('runtimePolicy') != pin['runtimePolicy']: raise ValueError('Wrong offline interop runtime policy')
    for name in [*pin['requiredFiles'], PLUGIN]:
        if name not in paths: raise ValueError(f'Missing required deployment file {name}')
    for name in paths:
        relative(name)
        if not deployment_path(name) or 'payload/' + name not in hashes: raise ValueError('Invalid deployment path')
    print(json.dumps({'target': manifest['target'], 'files': len(hashes), 'deploymentFiles': len(paths), 'gameFilesIncluded': False, 'realGameAcceptance': 'pending'}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true'); parser.add_argument('--verify', action='store_true')
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/windows-match-source-cache')
    parser.add_argument('--staging', type=Path, default=ROOT / 'build/windows-match-input')
    parser.add_argument('--plugin', type=Path, default=ROOT / 'build/match-plugin/FootballAssistant.MatchReader.dll')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/match-windows-x64')
    args = parser.parse_args()
    if args.prepare: prepare(args.cache, args.staging)
    elif args.verify: verify(args.output)
    else: assemble(args.cache, args.staging, args.plugin, args.output)
