"""Synthetic, model-free finite producer tests; no game access."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import json
import pytest
from football_assistant_data.storage import ObservationStore
from football_assistant_data.windows_finite_observations import *
from football_assistant_agent.ui_advice import prepare_current_page_attributes, prepare_ui_advice

NOW = datetime(2026,11,1,tzinfo=timezone.utc)

def fixture():
    bound = dict(pid=123,entry_tid=456,session_id=str(uuid4()),bridge_sha256='a'*64,game_sha256=GAME_SHA256,
                 batch_id=str(uuid4()),page_epoch=str(uuid4()),manifest_name='profile_rows0_3',window_class='UnityWndClass',first_nonce=str(uuid4()),second_nonce=str(uuid4()),expires_at=(NOW+timedelta(seconds=120)).isoformat())
    event = dict(bound,phase='finite_rows_chunk_result',schema_version=4,callback_tid=456,accepted=True,error=None,
                 page_identity_verified=False,snapshot_atomic=False,business_facts=False,chunk_index=0,
                 category_key='goalkeeper',row_start=0,row_count=2,declared_chunks=6,declared_units=12288,declared_ms=6000,nonce=bound['first_nonce'],selection_profile='goalkeeper_rows0_1',
                 capture_started_at=(NOW-timedelta(seconds=1)).isoformat(),capture_finished_at=NOW.isoformat())
    observations = [dict(Path=FOCUS['goalkeeper']+'/0',Text='守门')]
    for row,label in enumerate(CATEGORIES['goalkeeper']['labels'][:2]):
        prefix = FOCUS['goalkeeper']+'/2/0/0/0/'+str(row)
        observations += [dict(Path=prefix+LABEL_SUFFIX,Text=label),dict(Path=prefix+VALUE_SUFFIX,Text=str(8+row))]
    event['result'] = dict(Status='raw_diagnostics',Reason='approved_group_targets_complete',SelectionProfile='goalkeeper_rows0_1',Request=dict(SchemaVersion=3,Nonce=event['nonce'],ApprovalSha256='c'*64),PageIdentityVerified=False,PanelIndex=0,FocusPath=FOCUS['goalkeeper'],Observations=observations)
    session = {key:bound[key] for key in SOURCE_KEYS}; session['window_class']='UnityWndClass'
    return bound,event,[session,dict(session,state='ready'),dict(session,outcome='running',batch_id=bound['batch_id'],page_epoch=bound['page_epoch'],manifest_name=bound['manifest_name']),[event]]

class Lifetime:
    def alive(self): return True
    def close(self): pass

class Files:
    def __init__(self,parts): self.parts=parts
    def read_snapshot(self,root): return deepcopy(self.parts)

@pytest.fixture
def source(tmp_path):
    bound,event,parts=fixture(); store=ObservationStore(tmp_path/'store.sqlite',clock=lambda:NOW)
    reader=WindowsFiniteSource(store,tmp_path,bound,files=Files(parts),clock=lambda:NOW,lifetime=Lifetime())
    yield reader,event,parts,store
    store.close()

def test_ingest_existing_store_reader_and_agent_path(source):
    reader,event,parts,store=source;reader.poll()
    assert reader.reason=='fresh_chunk'
    snapshot=store.reader_snapshot()
    assert snapshot['observation']['source']['platform']=='windows-x64'
    preview=prepare_current_page_attributes(snapshot,now=NOW)
    assert preview['status']=='experimental_ui_current_page_attributes'
    assert preview['identity'] is None
    assert [r['value'] for r in preview['current_page_attributes']['groups'][0]['rows']]==[8,9]
    advice=prepare_ui_advice('player_info',snapshot,now=NOW)
    assert advice['status']=='ready' and advice['provenance']['captured_at']==event['capture_started_at']
    assert prepare_ui_advice('schedule_analysis',snapshot,now=NOW)['status']=='blocked'
    assert prepare_current_page_attributes(snapshot,now=NOW+timedelta(seconds=11))['current_page_attributes']['groups'][0]['rows'][0]['capture_freshness']=='stale'
    assert prepare_current_page_attributes(snapshot,now=NOW+timedelta(seconds=121))['status']=='unavailable'

def test_unchanged_file_never_touches_liveness(source):
    reader,event,parts,store=source;reader.poll(); before=store.source_status()
    reader.poll();assert store.source_status()['captures']==before['captures']==1

@pytest.mark.parametrize('mutate',[
    lambda p:p[0].update(session_id=str(uuid4())),
    lambda p:p[1].update(state='stopped'),
    lambda p:p[2].update(outcome='cancelled'),
    lambda p:p[3][0].update(chunk_index=1),
    lambda p:p[3][0].update(capture_started_at=(NOW-timedelta(seconds=121)).isoformat()),
    lambda p:p[3][0].update(capture_finished_at=(NOW+timedelta(seconds=1)).isoformat()),
    lambda p:p[3][0].update(category_key='mental'),
    lambda p:p[3][0].update(game_sha256='b'*64),
    lambda p:p[3][0].update(snapshot_atomic=True),
    lambda p:p[3][0]['result']['Observations'][2].update(Text='21'),
])
def test_reject_invalid(source,mutate):
    reader,event,parts,store=source;mutate(parts);reader.poll()
    assert reader.closed and store.latest() is None

def test_tamper_clears_current(source):
    reader,event,parts,store=source;reader.poll();parts[3][0]['result']['Observations'][2]['Text']='10';reader.poll()
    assert reader.closed and store.source_status()['connection_state']=='disconnected'
    assert prepare_current_page_attributes(store.reader_snapshot(),now=NOW)['status']=='unavailable'

def test_replay_and_truncation(source):
    reader,event,parts,store=source;reader.poll();parts[3].append(deepcopy(event));reader.poll();assert reader.closed

@pytest.mark.parametrize('key,value',[('manifest_name','arbitrary_rows'),('pid',True),('game_sha256','f'*64)])
def test_registration_does_not_trust_source(key,value):
    bound,_,_=fixture();bound[key]=value
    with pytest.raises(ValueError): registration(bound)


def test_exact_next_chunk_accumulates_only_same_registered_batch(source):
    reader,event,parts,store=source;reader.poll()
    second=deepcopy(event);second.update(capture_started_at=NOW.isoformat(),chunk_index=1,row_start=2,nonce=reader.bound['second_nonce'],selection_profile='goalkeeper_rows2_3')
    second['result']['SelectionProfile']=second['selection_profile'];second['result']['Request']['Nonce']=second['nonce']
    second['result']['Observations']=[dict(Path=FOCUS['goalkeeper']+'/0',Text='守门')]
    for row in (2,3):
        prefix=FOCUS['goalkeeper']+'/2/0/0/0/'+str(row)
        second['result']['Observations'] += [dict(Path=prefix+LABEL_SUFFIX,Text=CATEGORIES['goalkeeper']['labels'][row]),dict(Path=prefix+VALUE_SUFFIX,Text='11')]
    parts[3].append(second);reader.poll()
    snapshot=store.reader_snapshot(); projection=prepare_current_page_attributes(snapshot,now=NOW)['current_page_attributes']
    assert projection['chunk_index']==1
    assert [r['row_index'] for r in projection['groups'][0]['rows']]==[0,1,2,3]
    assert snapshot['facts_total']==8
    assert store.source_status()['captures']==2


def test_process_or_window_loss_invalidates(source):
    reader,event,parts,store=source;reader.poll()
    reader.lifetime.alive=lambda:False;reader.poll()
    assert reader.closed and store.source_status()['connection_state']=='disconnected'


def test_reserved_adapter_cannot_be_posted(tmp_path):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_data.config import Settings
    settings=Settings(data_dir=tmp_path,runtime_file=tmp_path/'runtime.json',token='test-only')
    with TestClient(create_app(settings,enable_agent=False),base_url='http://127.0.0.1') as client:
        assert client.post('/v1/observations',headers={'Authorization':'Bearer test-only'},json={'source':{'adapter_id':ADAPTER_ID}}).status_code==422
        assert client.get('/v1/reader/current-page-attributes',headers={'Authorization':'Bearer test-only'}).json()['status']=='unavailable'


def test_source_config_requires_explicit_private_root(monkeypatch):
    from football_assistant_data.config import Settings
    bound,_,_=fixture()
    monkeypatch.setenv('FOOTBALL_ASSISTANT_WINDOWS_FINITE_REGISTRATION',json.dumps(bound))
    monkeypatch.delenv('FOOTBALL_ASSISTANT_PRIVATE_ROOT',raising=False)
    with pytest.raises(ValueError): Settings.from_env(reader_only=True)


def test_ai_generation_rechecks_same_capture_without_model(source, monkeypatch):
    import asyncio
    import football_assistant_agent.service as service
    reader,event,parts,store=source;reader.poll();snapshot=store.reader_snapshot()
    real_prepare=service.prepare_ui_advice
    monkeypatch.setattr(service,'prepare_ui_advice',lambda c,s:real_prepare(c,s,now=NOW))
    agent=object.__new__(service.AgentService)
    async def chat(*args,**kwargs):
        assert kwargs=={'ui':True}
        assert args[2]['ui_evidence']['evidence'][0]['rows'][0]['value_display']=='8'
        return {'reply':'synthetic test response'}
    agent._chat=chat
    result=asyncio.run(agent.ui_advice('页面属性',None,'player_info',snapshot,refresh=lambda:snapshot))
    assert result['status']=='generated'
    reader.invalidate('cancelled')
    result=asyncio.run(agent.ui_advice('页面属性',None,'player_info',snapshot,refresh=store.reader_snapshot))
    assert result['status']=='blocked' and result['evidence']==[]


def test_one_full_manifest_all_35_rows_summary_retains_original_times(tmp_path):
    bound,template,parts=fixture();bound['manifest_name']='profile_all_rows'
    parts[2]['manifest_name']='profile_all_rows';parts[3]=[]
    tick=[NOW];store=ObservationStore(tmp_path/'full.sqlite',clock=lambda:tick[0])
    reader=WindowsFiniteSource(store,tmp_path,bound,files=Files(parts),clock=lambda:tick[0],lifetime=Lifetime())
    for index,(category,start,count) in enumerate(manifest_chunks(bound)):
        tick[0]=NOW+timedelta(seconds=3*index)
        nonce=bound['first_nonce'] if index==0 else bound['second_nonce'] if index==1 else str(UUID(bytes_le=hashlib.sha256(
            f"finite-rows-child-v1|{bound['batch_id']}|{bound['first_nonce']}|{bound['second_nonce']}|{index}".encode()).digest()[:16]))
        event=deepcopy(template);profile=f'{category}_rows{start}_{start+count-1}'
        event.update(manifest_name='profile_all_rows',chunk_index=index,category_key=category,row_start=start,row_count=count,
            declared_chunks=18,declared_units=36864,declared_ms=18000,nonce=nonce,selection_profile=profile,
            capture_started_at=(tick[0]-timedelta(seconds=1)).isoformat(),capture_finished_at=tick[0].isoformat())
        raw=event['result'];raw.update(SelectionProfile=profile,FocusPath=FOCUS[category]);raw['Request']['Nonce']=nonce
        raw['Observations']=[dict(Path=FOCUS[category]+'/0',Text=CATEGORIES[category]['title'])]
        for row in range(start,start+count):
            prefix=FOCUS[category]+'/2/0/0/0/'+str(row)
            raw['Observations'] += [dict(Path=prefix+LABEL_SUFFIX,Text=CATEGORIES[category]['labels'][row]),dict(Path=prefix+VALUE_SUFFIX,Text=str(row+1))]
        parts[3].append(event);reader.poll();assert not reader.closed
    parts[2]['outcome']='completed';reader.poll()
    snapshot=store.reader_snapshot(0,274);summary=prepare_current_page_attributes(snapshot,now=tick[0])['current_page_attributes']
    assert summary['progress']==dict(chunks_received=18,chunks_expected=18,rows_received=35,rows_expected=35,complete=True)
    assert summary['all_rows_current'] is False
    assert [len(g['rows']) for g in summary['groups']]==[13,14,8]
    assert summary['groups'][0]['rows'][0]['field_provenance']['capture_started_at']==parts[3][0]['capture_started_at']
    tick[0]+=timedelta(seconds=15);reader.poll()
    snapshot=store.reader_snapshot(0,274);assert snapshot['source_status']['data_freshness']=='stale'
    advice=prepare_ui_advice('player_info',snapshot,now=tick[0]);assert advice['status']=='ready'
    assert sum(len(g['rows']) for g in advice['evidence'])==35
    assert all(row['capture_freshness']=='stale' for g in advice['evidence'] for row in g['rows'])
    tick[0]=NOW+timedelta(seconds=121)
    assert prepare_current_page_attributes(store.reader_snapshot(),now=tick[0])['status']=='unavailable'
    store.close()


@pytest.mark.parametrize('seconds',[-1,0,121])
def test_registration_has_bounded_future_window(tmp_path,seconds):
    bound,_,parts=fixture();bound['expires_at']=(NOW+timedelta(seconds=seconds)).isoformat()
    with pytest.raises(ValueError,match='invalid_registration_window'):
        WindowsFiniteSource(None,tmp_path,bound,files=Files(parts),clock=lambda:NOW,lifetime=Lifetime())


def test_atomic_replace_missing_defers_without_refresh_then_invalidates(source):
    reader,event,parts,store=source;reader.poll()
    original=store.source_status();tick=[NOW];reader.clock=lambda:tick[0]
    def missing(_): raise FileNotFoundError('synthetic atomic replacement gap')
    reader.files.read_snapshot=missing
    reader.poll();assert not reader.closed and reader.reason=='awaiting_atomic_replacement'
    tick[0]+=timedelta(seconds=1);reader.poll()
    assert store.source_status()['last_seen_at']==original['last_seen_at']
    assert store.source_status()['last_captured_at']==original['last_captured_at']
    tick[0]+=timedelta(seconds=1);reader.poll()
    assert reader.closed and store.source_status()['connection_state']=='disconnected'


def test_atomic_replace_missing_recovers_and_permission_denied_fails_closed(source):
    reader,event,parts,store=source;reader.poll()
    read=reader.files.read_snapshot
    def missing(_): raise FileNotFoundError('synthetic replacement')
    reader.files.read_snapshot=missing;reader.poll()
    reader.files.read_snapshot=read;reader.poll()
    assert not reader.closed and reader.missing_since is None
    def denied(_): raise PermissionError('synthetic permission denial')
    reader.files.read_snapshot=denied;reader.poll()
    assert reader.closed and store.source_status()['connection_state']=='disconnected'
