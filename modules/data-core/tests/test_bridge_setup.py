import hashlib
import json
from pathlib import Path
import pytest
from football_assistant_data import bridge_setup as bridge

def setup(tmp_path):
    return bridge.BridgeSetup(tmp_path / 'user', tmp_path / 'payload', system='darwin', architecture='arm64')

def fake_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'inspect_game', lambda game: {'gamePath': str(game), 'gameVersion': bridge.GAME_VERSION, 'architecture': 'arm64', 'gameSha256': bridge.GAME_SHA})
    monkeypatch.setattr(bridge, 'validate_payload', lambda path: 'reviewed-payload-hash')
    monkeypatch.setattr(bridge, 'running_game', lambda: False)
    actions = []
    def prepare(game, destination, payload, apply):
        actions.append(apply)
        if apply:
            destination.mkdir(parents=True)
            (destination / 'synthetic').write_text('fixture only')
    monkeypatch.setattr(bridge, 'prepare', prepare)
    return actions

def test_windows_and_unknown_architecture_fail_closed(tmp_path):
    for system, architecture, reason in [('win32', 'amd64', 'unsupported_platform'), ('darwin', 'x86_64', 'unsupported_architecture')]:
        with pytest.raises(bridge.SetupError, match=reason):
            bridge.BridgeSetup(tmp_path, tmp_path/'payload', system=system, architecture=architecture).inspect()
    assert not (tmp_path/'bridge').exists()

def test_missing_payload_never_looks_deployable(tmp_path):
    result = setup(tmp_path).inspect()
    assert result['state'] == 'payload_unavailable' and result['canEnable'] is False and result['dataConnected'] is False

def test_plan_consent_deploy_rollback_preserve_original_and_private_copy(tmp_path, monkeypatch):
    actions = fake_ready(monkeypatch, tmp_path)
    game=tmp_path/'fm.app';game.mkdir();original=game/'original';original.write_text('do not change')
    manager=setup(tmp_path); plan=manager.plan(str(game))
    assert actions == [False] and plan['canEnable'] and not Path(plan['privateRoot']).exists()
    with pytest.raises(bridge.SetupError, match='consent_required'):manager.deploy(plan['planId'], False)
    assert actions == [False]
    result=manager.deploy(plan['planId'], True)
    assert actions == [False,True] and result['dataConnected'] is False and original.read_text()=='do not change'
    rolled=manager.rollback(); assert rolled['state']=='disabled'
    assert Path(plan['privateRoot']).is_dir() and original.read_text()=='do not change'
    assert manager.rollback()['state']=='disabled'  # retry after config write failure
    assert manager.plan(str(game))['planId'] != plan['planId']

def test_rechecks_game_running_expired_and_changed_payload(tmp_path, monkeypatch):
    fake_ready(monkeypatch,tmp_path); manager=setup(tmp_path); plan=manager.plan(str(tmp_path/'fm.app'))
    monkeypatch.setattr(bridge,'running_game',lambda:True)
    with pytest.raises(bridge.SetupError,match='game_running'):manager.deploy(plan['planId'],True)
    monkeypatch.setattr(bridge,'running_game',lambda:False)
    monkeypatch.setattr(bridge,'validate_payload',lambda path:'different')
    with pytest.raises(bridge.SetupError,match='payload_changed'):manager.deploy(plan['planId'],True)
    file=manager.root/'plans'/f"{plan['planId']}.json";value=json.loads(file.read_text(encoding="utf-8"));value['createdAt']=0;file.write_text(json.dumps(value))
    with pytest.raises(bridge.SetupError,match='expired_plan'):manager.deploy(plan['planId'],True)

def test_failure_cleans_only_fresh_instance(tmp_path,monkeypatch):
    fake_ready(monkeypatch,tmp_path); manager=setup(tmp_path); plan=manager.plan(str(tmp_path/'fm.app'))
    def failed(game,destination,payload,apply):
        destination.mkdir();(destination/'partial').write_text('partial');raise ValueError('failed fixture')
    monkeypatch.setattr(bridge,'prepare',failed)
    with pytest.raises(ValueError):manager.deploy(plan['planId'],True)
    assert not Path(plan['privateRoot']).exists() and not (manager.root/'deployment.json').exists()

def test_manifest_hashes_and_unlisted_payload_files_are_rejected(tmp_path):
    payload=tmp_path/'payload';files={}
    for name in ['compat/dist/bepinex-core/core.dll','compat/dist/dotnet-extras/extra.dll','runtime/libcoreclr.dylib','libdoorstop.dylib','FootballAssistant.GameBridge.dll']:
        file=payload/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'fixture');files[name]=hashlib.sha256(b'fixture').hexdigest()
    (payload/'payload.json').write_text(json.dumps({'schema':1,'target':'darwin-arm64','reviewed':True,'files':files}))
    assert bridge.validate_payload(payload)
    (payload/'runtime/extra.dll').write_bytes(b'unlisted')
    with pytest.raises(bridge.SetupError,match='payload_unlisted_file'):bridge.validate_payload(payload)
    (payload/'runtime/extra.dll').unlink();(payload/'libdoorstop.dylib').write_bytes(b'changed')
    with pytest.raises(bridge.SetupError,match='payload_hash_mismatch'):bridge.validate_payload(payload)

def test_forged_receipt_cannot_rollback_external_directory(tmp_path):
    manager=setup(tmp_path);manager.initialize()
    bridge.write_json(manager.root/'deployment.json',{'planId':'a'*32,'privateRoot':str(tmp_path)})
    with pytest.raises(bridge.SetupError,match='invalid_receipt'):manager.receipt()

def test_low_disk_space_blocks_before_copy_or_sign(tmp_path,monkeypatch):
    actions=fake_ready(monkeypatch,tmp_path);manager=setup(tmp_path)
    from types import SimpleNamespace
    monkeypatch.setattr(bridge.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    with pytest.raises(bridge.SetupError,match='insufficient_disk_space'):manager.plan(str(tmp_path/'fm.app'))
    assert True not in actions
