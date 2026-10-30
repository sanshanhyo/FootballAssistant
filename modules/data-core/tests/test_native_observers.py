"""Synthetic sanitized DTOs only: no native library, game, hook or model call."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from uuid import uuid4

from fastapi.testclient import TestClient
from football_assistant_data.app import create_app
from football_assistant_data.config import Settings
from football_assistant_data.native_observers import ANCHOR,COUNTERS,MAX_U64

AUTH={'Authorization':'Bearer synthetic-token'}
PATH='/v1/interfaces/native-observers'


def report():
    return {'adapter_id':'synthetic-native-observer','session_id':'synthetic-session','game_build':'synthetic-build','bundle_version':'synthetic-bundle','metadata_sha256':'a'*64,'game_assembly_sha256':'b'*64,'game_plugin_sha256':'c'*64,'observer_sha256':'d'*64,'captured_at':datetime.now(timezone.utc).isoformat(),'synthetic':True,'sample_id':uuid4().hex,'status':'available','abi_version':1,'target':{'kind':'dispatch_thunk','anchor_export':ANCHOR,'anchor_offset_bytes':12,'dispatch_rva':'0x16c24'},'installed':True,'capture_enabled':True,'install_state':3,**{name:'0' for name in COUNTERS},'records_total':'0','records':[],'payload_data_read':False,'complete':False,'field_values_known':False}


def header(**kwargs):
    return {'call_sequence':'1','native_thread_id':'123','keys_count':'0','payload_count':'0','flags':3,'age_seconds':2.0,**kwargs}


def client_for(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path,runtime_file=tmp_path/'runtime.json',token='synthetic-token')),base_url='http://127.0.0.1')


def ui(client,session='synthetic-session'):
    now=datetime.now(timezone.utc).isoformat()
    body={'schema_version':'0.2.0','event_id':str(uuid4()),'captured_at':now,'observed_at':now,'synthetic':True,'source':{'kind':'runtime','adapter_id':'synthetic-ui','adapter_version':'test','platform':'unknown','freshness':'live'},'game':{'product':'FM27','build':'synthetic-build','session_id':session,'game_time':None},'status':'partial','payload':{'kind':'fact_snapshot','facts':[{'entity_kind':'ui_element','entity_id':None,'field':'ui_tree_text','value':'Synthetic tree text'}]}}
    assert client.post('/v1/observations',headers=AUTH,json=body).status_code==200


def test_no_native_report_is_unknown_and_passive(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get(PATH).status_code==401
        assert client.get(PATH,headers=AUTH).json()['native_observers']==[]
        summary=client.get('/v1/monitoring',headers=AUTH).json()['native_observer_summary']
        assert summary['state']=='unknown' and summary['installed'] is None
        assert summary['observed_callback_count'] is None and summary['callback_observed'] is None
        assert client.get('/v1/status',headers=AUTH).json()['memory']['messages']==0


def test_uint64_strings_units_and_dispatch_scope_are_preserved(tmp_path):
    with client_for(tmp_path) as client:
        body=report()
        body.update(invocation_count=str(MAX_U64),enqueued_count='9007199254740993',records_total='1',latest_header_age_seconds=2.0,records=[header(call_sequence='9007199254740993',native_thread_id=str(MAX_U64),keys_count=str(MAX_U64))])
        response=client.post(PATH,headers=AUTH,json=body)
        assert response.status_code==200,response.text
        data=response.json()
        assert data['observed_callback_count']==str(MAX_U64)
        assert data['captured_header_count']=='9007199254740993'
        assert data['report']['records'][0]['keys_count']==str(MAX_U64)
        assert data['count_units']=={'keys_count':'uint64_elements','payload_count':'bytes'}
        assert data['report']['target']['kind']=='dispatch_thunk'
        assert data['report']['target']['anchor_offset_bytes']==12
        assert data['setter_export_readability_inferred'] is False
        assert data['field_values_known'] is False and data['payload_decoded'] is False
        assert data['original_callback_success_known'] is False and data['complete'] is False
        assert client.get('/v1/interfaces/catalogs',headers=AUTH).json()['catalogs']==[]
        assert client.get('/v1/status',headers=AUTH).json()['source_status']['source'] is None


def test_uint64_numbers_overflow_and_bad_encodings_rejected(tmp_path):
    with client_for(tmp_path) as client:
        for value in [0,9007199254740993,1.0,True,'-1','01','1e3',str(MAX_U64+1)]:
            body=report();body['invocation_count']=value
            assert client.post(PATH,headers=AUTH,json=body).status_code==422
        body=report();body['records']=[header()]*17;body['records_total']='17'
        assert client.post(PATH,headers=AUTH,json=body).status_code==422


def test_unknown_flags_and_known_zero_do_not_collapse(tmp_path):
    with client_for(tmp_path) as client:
        unknown=report()
        unknown.update(status='not_probed',installed=None,capture_enabled=None,install_state=None,records_total=None,**{name:None for name in COUNTERS})
        data=client.post(PATH,headers=AUTH,json=unknown).json()
        assert data['observed_callback_count'] is None and data['callback_observed'] is None
        zero=report()
        data=client.post(PATH,headers=AUTH,json=zero).json()
        assert data['observed_callback_count']=='0' and data['callback_observed'] is False
        body=report();body.update(records_total='1',records=[header(flags=32,native_thread_id=None,keys_count=None,payload_count=None,age_seconds=None)])
        data=client.post(PATH,headers=AUTH,json=body).json()
        assert data['report']['records'][0]['keys_count'] is None
        body['records'][0]['keys_count']='0'
        assert client.post(PATH,headers=AUTH,json=body).status_code==422
        body=report();body.update(records_total='1',records=[header()])
        assert client.post(PATH,headers=AUTH,json=body).status_code==200


def test_last_callback_not_poll_time_and_no_counter_event_spam(tmp_path):
    with client_for(tmp_path) as client:
        first=report();first.update(invocation_count='1',enqueued_count='1',records_total='1',records=[header()])
        result=client.post(PATH,headers=AUTH,json=first).json()
        key=result['observer_key'];callback_at=result['last_callback_at']
        assert callback_at is not None and callback_at!=result['last_seen_at']
        assert client.post(PATH,headers=AUTH,json=first).json()['duplicate'] is True
        collision=deepcopy(first);collision['invocation_count']='2'
        assert client.post(PATH,headers=AUTH,json=collision).status_code==409
        later=report();later['captured_at']=(datetime.fromisoformat(first['captured_at'])+timedelta(seconds=1)).isoformat();later['invocation_count']='2';later['enqueued_count']='1'
        second=client.post(PATH,headers=AUTH,json=later).json()
        assert second['last_callback_at']==callback_at
        repeated=deepcopy(later);repeated['sample_id']=uuid4().hex;repeated['captured_at']=(datetime.fromisoformat(later['captured_at'])+timedelta(seconds=1)).isoformat()
        assert client.post(PATH,headers=AUTH,json=repeated).json()['changed'] is False
        history=client.get(PATH+'/history',params={'observer_key':key},headers=AUTH).json()['history']
        assert len(history)==2
        events=client.get('/v1/events',headers=AUTH).json()['events']
        assert len([event for event in events if event['kind']=='native_observer_state_changed'])==1
        old=report();old['captured_at']=(datetime.fromisoformat(first['captured_at'])-timedelta(hours=1)).isoformat();old['invocation_count']='999'
        ignored=client.post(PATH,headers=AUTH,json=old).json()
        assert ignored['ignored_out_of_order'] is True and ignored['observed_callback_count']=='2'


def test_pointers_false_completeness_and_setter_claim_are_rejected_without_echo(tmp_path):
    with client_for(tmp_path) as client:
        for mutation in ['pointer','setter','offset','field_values','payload','complete']:
            body=report()
            if mutation=='pointer':body['install_report']={'target_address':'0xDEADBEEF','original_address':'0xBADCAFE'}
            if mutation=='setter':body['target']['kind']='setter_export'
            if mutation=='offset':body['target']['anchor_offset_bytes']=0
            if mutation=='field_values':body['field_values_known']=True
            if mutation=='payload':body['payload_data_read']=True
            if mutation=='complete':body['complete']=True
            response=client.post(PATH,headers=AUTH,json=body)
            assert response.status_code==422
            assert 'DEADBEEF' not in response.text and 'BADCAFE' not in response.text
        assert client.get(PATH,headers=AUTH).json()['native_observers']==[]


def test_active_session_and_restart_do_not_reuse_old_installed_state(tmp_path):
    with client_for(tmp_path) as client:
        ui(client)
        body=report()
        assert client.post(PATH,headers=AUTH,json=body).status_code==200
        summary=client.get('/v1/monitoring',headers=AUTH).json()['native_observer_summary']
        assert summary['installed'] is True and summary['state']=='waiting_callbacks'
        ui(client,'synthetic-other-session')
        summary=client.get('/v1/monitoring',headers=AUTH).json()['native_observer_summary']
        assert summary['state']=='unknown' and summary['installed'] is None
    with client_for(tmp_path) as client:
        assert len(client.get(PATH,headers=AUTH).json()['native_observers'])==1
        ui(client)
        summary=client.get('/v1/monitoring',headers=AUTH).json()['native_observer_summary']
        assert summary['installed'] is None and summary['reported_installed'] is True
        assert summary['report_connection_state']=='disconnected'


def test_native_history_and_lists_are_byte_bounded(tmp_path):
    with client_for(tmp_path) as client:
        for index in range(80):
            body=report();body['session_id']=f'synthetic-session-{index}';body['reason']='诊'*1000
            body['records_total']='16';body['records']=[header(call_sequence=str(number+1),keys_count=str(MAX_U64),payload_count=str(MAX_U64)) for number in range(16)]
            assert client.post(PATH,headers=AUTH,json=body).status_code==200
        after=0;keys=[];pages=0
        while True:
            response=client.get(PATH,params={'after':after,'limit':100},headers=AUTH)
            assert len(response.content)<=512*1024
            data=response.json();pages+=1
            keys.extend(row['observer_key'] for row in data['native_observers'])
            if data['native_observers']:assert data['next_cursor']>after
            after=data['next_cursor']
            if not data['has_more']:break
        assert len(keys)==80 and len(set(keys))==80 and pages>1
        assert len(client.get('/v1/monitoring',headers=AUTH).content)<=512*1024
