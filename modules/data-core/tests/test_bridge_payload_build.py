import importlib.util
import io
import json
from pathlib import Path
import tarfile
import zipfile
import pytest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('payload_build',ROOT/'scripts/build_bridge_payload.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

def test_payload_urls_and_archive_paths_fail_closed(tmp_path):
    for url in ['http://github.com/test','https://evil.example/file','https://user:pass@github.com/file']:
        with pytest.raises(ValueError):builder.trusted_url(url)
    for path in ['../escape','/absolute',r'C:\absolute',r'..\escape','C:relative']:
        with pytest.raises(ValueError):builder.put_bytes(tmp_path,path,b'fixture')

def test_candidate_collects_notices_source_and_stays_unreviewed(tmp_path,monkeypatch):
    cache=tmp_path/'cache';cache.mkdir();plugin=tmp_path/'bridge.dll';plugin.write_bytes(b'MZsynthetic-fixture-not-loadable')
    library=b'library-fixture'
    with zipfile.ZipFile(cache/'doorstop.zip','w') as z:z.writestr('universal/libdoorstop.dylib',library);z.writestr('LICENSE',b'complete license fixture')
    (cache/'doorstop-source.tar.gz').write_bytes(b'source-fixture')
    with tarfile.open(cache/'dotnet-runtime.tar.gz','w:gz') as t:
        for name in ['LICENSE.txt','ThirdPartyNotices.txt']+[f'shared/Microsoft.NETCore.App/10.0.14/{name}' for name in ['libcoreclr.dylib']+[f'fixture{i}.dll' for i in range(100)]]:
            info=tarfile.TarInfo('./'+name);info.size=7;t.addfile(info,io.BytesIO(b'fixture'))
    lock=json.loads(builder.LOCK.read_text());lock['doorstop']['librarySha256']=__import__('hashlib').sha256(library).hexdigest();lockfile=tmp_path/'lock.json';lockfile.write_text(json.dumps(lock))
    monkeypatch.setattr(builder,'LOCK',lockfile);monkeypatch.setattr(builder,'download',lambda *args:None)
    report=builder.build(plugin,tmp_path/'candidate',cache)
    manifest=json.loads((tmp_path/'candidate/payload.json').read_text())
    assert manifest['reviewed'] is False and report['gameFilesIncluded'] is False
    assert 'licenses/dotnet-ThirdPartyNotices.txt' in manifest['files']
    assert 'licenses/FootballAssistant-LICENSE' in manifest['files']
    assert 'sources/FootballAssistant-GameBridge-source.tar.gz' in manifest['files']
    assert any(name.startswith('sources/UnityDoorstop-') for name in manifest['files'])
    with pytest.raises(ValueError,match='already exists'):builder.build(plugin,tmp_path/'candidate',cache)
