"""All captures/catalog entries below are synthetic; no game or model calls."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from football_assistant_data.app import create_app
from football_assistant_data.config import Settings
from football_assistant_data.storage import ObservationConflict,ObservationStore


class Clock:
    def __init__(self):
        self.now=datetime(2026,10,30,tzinfo=timezone.utc)
        self.tick=100.0
    def advance(self,seconds):
        self.now+=timedelta(seconds=seconds)
        self.tick+=seconds


def snapshot(clock,*,text="主界面",kind="runtime",session="synthetic-session",build="synthetic-build",adapter="synthetic-adapter"):
    source={"kind":kind,"adapter_id":adapter,"adapter_version":"test-only","platform":"unknown","freshness":"live" if kind=="runtime" else "snapshot"}
    if kind=="save":source["save_metadata"]={"snapshot_ref":"synthetic-copy","sha256":"a"*64,"file_modified_at":None,"parse_profile":"synthetic-profile"}
    return {"schema_version":"0.2.0","event_id":str(uuid4()),"captured_at":clock.now.isoformat(),"observed_at":clock.now.isoformat(),"synthetic":True,"source":source,"game":{"product":"FM27","build":build,"session_id":session,"game_time":None},"status":"available","payload":{"kind":"fact_snapshot","facts":[{"entity_kind":"ui_element","entity_id":"/synthetic/path","field":"visible_text","value":text}]}}


def store(tmp_path,clock):
    return ObservationStore(tmp_path/"observations.sqlite",clock=lambda:clock.now,monotonic=lambda:clock.tick)


def test_continuous_capture_dedup_heartbeat_changes_and_cursor(tmp_path):
    clock=Clock()
    db=store(tmp_path,clock)
    first=snapshot(clock)
    inserted=db.ingest(first)
    cursor=db.events()["latest_cursor"]
    clock.advance(3)
    same=snapshot(clock)
    assert db.ingest(same)["content_unchanged"] is True
    assert db.source_status()["last_seen_at"]==clock.now.isoformat()
    assert db.events(cursor)["events"]==[]
    assert db._db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
    assert db._db.execute('SELECT COUNT(*) FROM observation_receipts').fetchone()[0]==2
    clock.advance(3)
    changed=snapshot(clock,text="新的页面原文")
    assert db.ingest(changed)["content_unchanged"] is False
    page=db.events(cursor,1)
    assert page["events"][0]["kind"]=="ui_text_changed"
    assert page["events"][0]["details"]["semantic_level"]=="raw_observation"
    assert db.events(page["next_cursor"])["events"]==[]
    assert db.events(999)["cursor_reset_required"] is True
    assert db.ingest(changed)["duplicate"] is True
    conflict=deepcopy(changed)
    conflict['payload']['facts'][0]['value']='changed same UUID'
    with pytest.raises(ObservationConflict):db.ingest(conflict)
    db.close()


def test_connection_is_monotonic_and_heartbeat_does_not_refresh_capture(tmp_path):
    clock=Clock()
    db=store(tmp_path,clock)
    result=db.ingest(snapshot(clock))
    clock.advance(11)
    assert db.source_status()["connection_state"]=="stale"
    # Wall time can change, but transport timeout follows monotonic elapsed time.
    clock.now-=timedelta(hours=1)
    clock.tick+=20
    assert db.source_status()["connection_state"]=="disconnected"
    db.heartbeat(result["stream_id"],"connected")
    status=db.source_status()
    assert status["connection_state"]=="connected"
    assert status["last_captured_at"]!=status["last_seen_at"]
    db.heartbeat(result["stream_id"],"disconnected","synthetic clean shutdown")
    assert db.source_status()["connection_state"]=="disconnected"
    db.close()


def test_old_save_and_out_of_order_capture_do_not_replace_active_runtime(tmp_path):
    clock=Clock()
    db=store(tmp_path,clock)
    runtime=snapshot(clock,text="运行时")
    runtime_id=db.ingest(runtime)["stream_id"]
    clock.advance(2)
    db.ingest(snapshot(clock,text="存档",kind="save",adapter="synthetic-save"))
    assert db.source_status()["source"]=="runtime"
    assert db.context()["facts"][0]["value"]=="运行时"
    older=deepcopy(runtime)
    older["event_id"]=str(uuid4())
    older["captured_at"]=(clock.now-timedelta(minutes=1)).isoformat()
    older["payload"]["facts"][0]["value"]="旧捕获"
    assert db.ingest(older)["ignored_out_of_order"] is True
    assert db.context()["facts"][0]["value"]=="运行时"
    clock.advance(31)
    assert db.source_status()["source"]=="save"
    assert any(row["stream_id"]==runtime_id and row["connection_state"]=="disconnected" for row in db.monitoring()["streams"])
    db.close()


def test_session_build_separation_and_restart_needs_new_heartbeat(tmp_path):
    clock=Clock()
    db=store(tmp_path,clock)
    first=db.ingest(snapshot(clock))
    clock.advance(1)
    second=db.ingest(snapshot(clock,session="synthetic-session-two",build="synthetic-build-two"))
    assert first["stream_id"]!=second["stream_id"]
    assert len(db.monitoring()["streams"])==2
    cursor=db.events()["latest_cursor"]
    db.close()
    db=store(tmp_path,clock)
    assert all(row["connection_state"]=="disconnected" for row in db.monitoring()["streams"])
    assert any(event['details'].get('reason')=='backend_restart' for event in db.events(cursor)['events'])
    db.heartbeat(second["stream_id"],"connected")
    assert db.source_status()["stream_id"]==second["stream_id"]
    db.close()


def catalog(clock,*,records=None,complete=True,total=1):
    return {"catalog_id":"synthetic-catalog","catalog_version":"synthetic-v1","adapter_id":"synthetic-adapter","game_build":"synthetic-build","session_id":None,"metadata_sha256":"b"*64,"metadata_version":39,"captured_at":clock.now.isoformat(),"synthetic":True,"total_expected":total,"complete":complete,"records":records or [{"interface_id":"synthetic-event","assembly":"synthetic","namespace":"","type":"Synthetic.Type","member_kind":"event","name":"Changed","signature":"event Changed","visibility":"public","is_static":False,"access_status":"not_probed","reason":"Metadata enumeration only","side_effect_policy":"do_not_invoke","declaring_token":"0x14000001","parameters":[]}]}


def test_catalog_inventory_separate_from_verified_runtime_coverage(tmp_path):
    clock=Clock()
    settings=Settings(data_dir=tmp_path,runtime_file=tmp_path/'runtime.json',token='synthetic-token')
    headers={"Authorization":"Bearer synthetic-token"}
    with TestClient(create_app(settings),base_url='http://127.0.0.1') as client:
        assert client.get('/v1/monitoring').status_code==401
        body=catalog(clock)
        assert client.post('/v1/interfaces/catalog',headers=headers,json=body).status_code==200
        coverage=client.get('/v1/interfaces/catalogs',headers=headers).json()['catalogs'][0]
        assert coverage['inventory_complete'] is True
        assert coverage['runtime_verified_coverage']['verified_readable']==0
        records=client.get('/v1/interfaces',params={'catalog_id':body['catalog_id']},headers=headers).json()
        assert records['interfaces'][0]['member_kind']=='event'
        assert records['interfaces'][0]['access_status']=='not_probed'
        invalid=deepcopy(body)
        invalid['records'][0]['access_status']='verified_readable'
        assert client.post('/v1/interfaces/catalog',headers=headers,json=invalid).status_code==422
        conflict=deepcopy(body)
        conflict['metadata_sha256']='c'*64
        assert client.post('/v1/interfaces/catalog',headers=headers,json=conflict).status_code==409
        assert client.get('/v1/monitoring',headers=headers).json()['automatic_model_calls'] is False
        # Registered metadata cannot consume a model request; the companion store
        # remains empty throughout this monitoring-only API test.
        assert client.get('/v1/status',headers=headers).json()['memory']['messages']==0


def test_catalog_batches_are_idempotent_and_inventory_does_not_erase_probe(tmp_path):
    clock=Clock()
    db=store(tmp_path,clock)
    first=catalog(clock,complete=False,total=2)
    assert db.register_catalog(first)["registered_count"]==1
    assert db.register_catalog(first)["registered_count"]==1
    second=deepcopy(first)
    second["records"][0]["interface_id"]="synthetic-property"
    second["records"][0]["member_kind"]="property"
    second["complete"]=True
    assert db.register_catalog(second)["complete"] is True
    probe=deepcopy(second)
    probe["complete"]=False
    probe["session_id"]="synthetic-session"
    probe["records"][0].update(access_status="verified_readable",side_effect_policy="read_only",verification="Synthetic measured getter fixture",last_verified_at=clock.now.isoformat(),field_paths=["ui_element.visible_text"])
    db.register_catalog(probe)
    db.register_catalog(second)
    status=db.catalogs()["catalogs"][0]
    assert status["inventory_complete"] is True
    assert status["registered_count"]==2
    assert status["inventory_kind"]=="managed_metadata"
    assert status["runtime_verified_coverage"]["verified_readable"]==1
    assert status["runtime_verified_coverage"]["continuous_monitoring_implied"] is False
    measured = db.interfaces("synthetic-catalog",access_status="verified_readable")["interfaces"][0]
    assert measured["side_effect_policy"]=="read_only"
    assert measured["field_paths"]==["ui_element.visible_text"]
    db.close()


def test_null_identity_text_multiplicity_is_a_low_level_change(tmp_path):
    clock=Clock()
    db=store(tmp_path,clock)
    first=snapshot(clock)
    first["payload"]["facts"][0]["entity_id"]=None
    db.ingest(first)
    after=db.events()["latest_cursor"]
    clock.advance(3)
    second=deepcopy(first)
    second.update(event_id=str(uuid4()),captured_at=clock.now.isoformat(),observed_at=clock.now.isoformat())
    second["payload"]["facts"].append(deepcopy(second["payload"]["facts"][0]))
    db.ingest(second)
    event=db.events(after)["events"][0]
    assert event["kind"]=="ui_text_changed"
    assert event["details"]["added_count"]==1
    db.close()


def encoded_size(value):
    return len(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8'))


def test_large_chinese_event_backlog_pages_progress_with_final_byte_budget(tmp_path):
    from football_assistant_contracts.validation import validate_observation
    from football_assistant_data.storage import EVENT_PAGE_BYTE_BUDGET
    clock=Clock()
    db=store(tmp_path,clock)
    for frame in range(25):
        body=snapshot(clock)
        body['payload']['facts']=[{'entity_kind':'ui_element','entity_id':f'/synthetic/{index}','field':'visible_text','value':f'{frame}'+('中'*999)} for index in range(40)]
        validate_observation(body)
        assert encoded_size(body)<128*1024
        db.ingest(body)
        clock.advance(3)
    cursor=0
    consumed=[]
    pages=0
    while True:
        page=db.events(cursor,100)
        pages+=1
        assert encoded_size(page)<=EVENT_PAGE_BYTE_BUDGET
        if page['events']:
            assert page['next_cursor']>cursor
            consumed.extend(event['cursor'] for event in page['events'])
        cursor=page['next_cursor']
        if not page['has_more']:break
        assert pages<100
    assert pages>1
    assert len(consumed)==len(set(consumed))
    assert len(consumed)==db._db.execute('SELECT COUNT(*) FROM change_events').fetchone()[0]
    empty=db.events(cursor,100)
    assert empty['events']==[] and empty['next_cursor']==cursor and empty['has_more'] is False
    assert encoded_size(db.monitoring())<=EVENT_PAGE_BYTE_BUDGET
    assert db.events(cursor+100)['cursor_reset_required'] is True
    db.close()


def test_single_oversize_event_has_explicit_summary_and_lossless_reference(tmp_path):
    from football_assistant_data.storage import EVENT_PAGE_BYTE_BUDGET
    clock=Clock()
    db=store(tmp_path,clock)
    original={'semantic_level':'raw_observation','added_count':1,'payload':'巨'*300000}
    with db._db:db._emit('ui_text_changed',None,None,True,original)
    page=db.events(0,100)
    assert encoded_size(page)<=EVENT_PAGE_BYTE_BUDGET
    assert page['next_cursor']==1 and page['has_more'] is False
    event=page['events'][0]
    assert event['details_truncated'] is True
    assert event['details']['summary_only'] is True
    assert event['original_event_ref']=='/v1/events/1'
    assert db.event_detail(1)['details']==original
    assert db.event_detail(1)['details_truncated'] is False
    assert db.events(1)['events']==[]
    assert encoded_size(db.monitoring())<=EVENT_PAGE_BYTE_BUDGET
    db.close()


def test_polling_http_bytes_and_explicit_original_detail_route(tmp_path):
    from football_assistant_data.storage import EVENT_PAGE_BYTE_BUDGET
    settings=Settings(data_dir=tmp_path,runtime_file=tmp_path/'runtime.json',token='synthetic-token')
    headers={'Authorization':'Bearer synthetic-token'}
    with TestClient(create_app(settings),base_url='http://127.0.0.1') as client:
        db=client.app.state.observations
        with db._db:db._emit('ui_text_changed',None,None,True,{'payload':'中'*300000})
        events=client.get('/v1/events?after=0&limit=100',headers=headers)
        monitoring=client.get('/v1/monitoring',headers=headers)
        assert len(events.content)<=EVENT_PAGE_BYTE_BUDGET
        assert len(monitoring.content)<=EVENT_PAGE_BYTE_BUDGET
        summary=events.json()['events'][0]
        assert summary['details_truncated'] is True
        assert client.get(summary['original_event_ref']).status_code==401
        original=client.get(summary['original_event_ref'],headers=headers)
        assert original.status_code==200 and original.json()['details']=={'payload':'中'*300000}
        assert original.json()['details_truncated'] is False
        assert client.get('/v1/events?after=1',headers=headers).json()['events']==[]


def test_native_inventory_is_separate_and_does_not_imply_readability(tmp_path):
    clock=Clock()
    settings=Settings(data_dir=tmp_path,runtime_file=tmp_path/'runtime.json',token='synthetic-token')
    headers={'Authorization':'Bearer synthetic-token'}
    with TestClient(create_app(settings),base_url='http://127.0.0.1') as client:
        managed=catalog(clock)
        assert client.post('/v1/interfaces/catalog',headers=headers,json=managed).status_code==200
        native=catalog(clock)
        native.update(catalog_id='synthetic-native-catalog',inventory_kind='native_exports',native_module='synthetic/module',native_module_sha256='d'*64)
        native['records'][0].update(interface_id='synthetic-native-symbol',member_kind='native_export',is_static=None)
        assert client.post('/v1/interfaces/catalog',headers=headers,json=native).status_code==200
        catalogs=client.get('/v1/interfaces/catalogs',headers=headers).json()['catalogs']
        assert len(catalogs)==2
        assert {item.get('inventory_kind') for item in catalogs}=={'managed_metadata','native_exports'}
        assert all(item['runtime_verified_coverage']['verified_readable']==0 for item in catalogs)
        invalid=deepcopy(native)
        invalid['records'][0]['side_effect_policy']='read_only'
        assert client.post('/v1/interfaces/catalog',headers=headers,json=invalid).status_code==422
        invalid=deepcopy(native)
        invalid['native_module_sha256']=None
        assert client.post('/v1/interfaces/catalog',headers=headers,json=invalid).status_code==422
