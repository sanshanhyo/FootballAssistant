"""Synthetic passive diagnostics only; never accesses game processes or models."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json

from fastapi.testclient import TestClient
from football_assistant_data.app import create_app
from football_assistant_data.config import Settings

HEADERS={'Authorization':'Bearer synthetic-token'}


def fixture():
    return {'adapter_id':'synthetic-runtime-inspector','session_id':'synthetic-session','game_build':'synthetic-build','bundle_version':'synthetic-bundle','metadata_sha256':'a'*64,'game_assembly_sha256':'b'*64,'captured_at':'2026-10-30T00:00:00Z','synthetic':True,'probes':[{'probe_id':'registry:PropertyIdentifierSet','kind':'runtime_registry','status':'available','context_ref':'session/synthetic/registry/PropertyIdentifierSet','reason':'Synthetic existing-context counts only','values':{'id_count':123,'name_hash_count':4},'enumeration':{'enumeration_id':'synthetic-enumeration','expected_entries':123,'observed_unique_entries':0,'complete':False},'entries':[]}]}


def client_for(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path,runtime_file=tmp_path/'runtime.json',token='synthetic-token')),base_url='http://127.0.0.1')


def test_counts_do_not_mean_entries_or_game_field_values(tmp_path):
    with client_for(tmp_path) as client:
        assert client.post('/v1/interfaces/probes',json=fixture()).status_code==401
        response=client.post('/v1/interfaces/probes',headers=HEADERS,json=fixture())
        assert response.status_code==200,response.text
        result=response.json()['results'][0]
        assert result['values']['id_count']==123
        assert result['enumeration']['observed_unique_entries']==0
        assert result['enumeration']['complete'] is False
        assert result['field_values_known'] is False
        assert client.get('/v1/status',headers=HEADERS).json()['source_status']['source'] is None
        summary=client.get('/v1/monitoring',headers=HEADERS).json()['registry_summary']
        assert summary['registry_count']==1 and summary['status_counts']['available']==1
        assert client.get('/v1/status',headers=HEADERS).json()['memory']['messages']==0


def test_repeat_probe_updates_capture_without_history_or_event_spam(tmp_path):
    with client_for(tmp_path) as client:
        first=client.post('/v1/interfaces/probes',headers=HEADERS,json=fixture()).json()
        key=first['results'][0]['probe_key']
        body=fixture()
        body['captured_at']='2026-10-30T00:00:03Z'
        repeated=client.post('/v1/interfaces/probes',headers=HEADERS,json=body).json()
        assert repeated['changed_count']==0
        history=client.get('/v1/interfaces/probes/history',params={'probe_key':key},headers=HEADERS).json()
        assert len(history['history'])==1
        events=client.get('/v1/events',headers=HEADERS).json()['events']
        assert len([event for event in events if event['kind']=='registry_probe_changed'])==1
        latest=client.get('/v1/interfaces/probes',headers=HEADERS).json()['probes'][0]
        assert latest['captured_at'].endswith('03Z')


def test_unknown_counts_are_not_empty_and_self_declared_complete_rejected(tmp_path):
    with client_for(tmp_path) as client:
        body=fixture()
        probe=body['probes'][0]
        probe.update(status='needs_context',values={'id_count':None,'name_hash_count':None})
        probe['enumeration'].update(expected_entries=None)
        result=client.post('/v1/interfaces/probes',headers=HEADERS,json=body).json()['results'][0]
        assert result['known_count_fields']==[]
        assert result['values']['id_count'] is None
        assert result['enumeration']['known_empty'] is False
        fake=fixture()
        fake['probes'][0]['enumeration'].update(observed_unique_entries=123,complete=True)
        assert client.post('/v1/interfaces/probes',headers=HEADERS,json=fake).status_code==409
        fake=fixture()
        fake['probes'][0]['entries']=[{'id':1}]
        assert client.post('/v1/interfaces/probes',headers=HEADERS,json=fake).status_code==422


def test_probe_session_partition_older_capture_and_history_cursor(tmp_path):
    with client_for(tmp_path) as client:
        first=client.post('/v1/interfaces/probes',headers=HEADERS,json=fixture()).json()['results'][0]
        changed=fixture()
        changed['captured_at']='2026-10-30T00:00:05Z'
        changed['probes'][0]['status']='error'
        assert client.post('/v1/interfaces/probes',headers=HEADERS,json=changed).status_code==200
        older=client.post('/v1/interfaces/probes',headers=HEADERS,json=fixture()).json()['results'][0]
        assert older['ignored_out_of_order'] is True and older['status']=='error'
        params={'probe_key':first['probe_key'],'limit':1}
        history1=client.get('/v1/interfaces/probes/history',headers=HEADERS,params=params).json()
        history2=client.get('/v1/interfaces/probes/history',headers=HEADERS,params={**params,'after':history1['next_cursor']}).json()
        assert history2['next_cursor']>history1['next_cursor']
        assert history2['history'][0]['status']=='error'
        new_session=fixture()
        new_session['session_id']='synthetic-session-two'
        second=client.post('/v1/interfaces/probes',headers=HEADERS,json=new_session).json()['results'][0]
        assert second['probe_key']!=first['probe_key']
        assert len(client.get('/v1/interfaces/probes',headers=HEADERS).json()['probes'])==2


def batch(*,expected=2,enumeration='synthetic-enumeration',complete=False,entries=None,version=None):
    body=fixture()
    body.pop('probes')
    return {**body,'registry_id':'PropertyIdentifierSet','enumeration_id':enumeration,'dictionary_version':version,'expected_count':expected,'complete':complete,'entries':[] if entries is None else entries}


def test_uint_registry_batches_authoritative_completion_and_probe_binding(tmp_path):
    with client_for(tmp_path) as client:
        probe=fixture()
        probe['probes'][0]['values']['id_count']=2
        probe['probes'][0]['enumeration']['expected_entries']=2
        first=client.post('/v1/interfaces/probes',headers=HEADERS,json=probe).json()['results'][0]
        assert first['enumeration']['observed_unique_entries']==0 and first['enumeration']['complete'] is False
        one=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(entries=[{'id':0}]))
        assert one.status_code==200,one.text
        key=one.json()['enumeration_key']
        assert one.json()['observed_unique_entries']==1 and one.json()['complete'] is False
        live=client.get('/v1/interfaces/probes',headers=HEADERS).json()['probes'][0]
        assert live['enumeration']['observed_unique_entries']==1 and live['enumeration']['complete'] is False
        final=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(complete=True,entries=[{'id':4294967295,'name':'真实类型的合成标签'}]))
        assert final.status_code==200 and final.json()['complete'] is True
        duplicate=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(entries=[{'id':0}])).json()
        assert duplicate['inserted_count']==0 and duplicate['observed_unique_entries']==2 and duplicate['complete'] is True
        live=client.get('/v1/interfaces/probes',headers=HEADERS).json()['probes'][0]
        assert live['enumeration']['complete'] is True and live['field_values_known'] is False
        entries=client.get(f'/v1/interfaces/registries/{key}/entries',headers=HEADERS).json()
        assert {entry['id'] for entry in entries['entries']}=={0,4294967295}
        assert all(entry['field_values_known'] is False for entry in entries['entries'])
        assert entries['entries'][0]['name'] is None
        assert client.get('/v1/status',headers=HEADERS).json()['source_status']['source'] is None


def test_epoch_expected_version_hash_conflicts_and_no_fake_final(tmp_path):
    with client_for(tmp_path) as client:
        initial=batch(expected=3,version=7,entries=[{'id':1,'name':'first'}])
        first=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=initial).json()
        key=first['enumeration_key']
        invalid=deepcopy(initial)
        invalid['complete']=True
        assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=invalid).status_code==409
        for field,value in [('expected_count',4),('dictionary_version',8),('game_build','changed-build'),('metadata_sha256','c'*64)]:
            invalid=deepcopy(initial)
            invalid[field]=value
            assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=invalid).status_code==409
        changed=deepcopy(initial)
        changed['entries'][0]['name']='changed inside epoch'
        assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=changed).status_code==409
        assert client.get(f'/v1/interfaces/registries/{key}',headers=HEADERS).json()['observed_unique_entries']==1
        next_epoch=deepcopy(initial)
        next_epoch['enumeration_id']='synthetic-next-epoch'
        new=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=next_epoch).json()
        assert new['enumeration_key']!=key and new['observed_unique_entries']==1
        # A diagnostic declaration pins expected/version before any entries exist.
        declared=fixture()
        declared['probes'][0]['enumeration']['enumeration_id']='declared-epoch'
        assert client.post('/v1/interfaces/probes',headers=HEADERS,json=declared).status_code==200
        # Simulate the probe-only release, which had no epoch descriptor row.
        db=client.app.state.observations._db
        with db:db.execute("DELETE FROM registry_enumerations WHERE enumeration_id=?",('declared-epoch',))
        mismatch=batch(expected=124,enumeration='declared-epoch',entries=[{'id':1}])
        assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=mismatch).status_code==409
        assert client.get('/v1/monitoring',headers=HEADERS).status_code==200


def test_unknown_empty_and_bad_uint_are_distinct(tmp_path):
    with client_for(tmp_path) as client:
        unknown=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(expected=None,enumeration='unknown')).json()
        assert unknown['expected_count'] is None and unknown['known_empty'] is False and unknown['complete'] is False
        assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(expected=None,enumeration='unknown',complete=True)).status_code==422
        empty=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(expected=0,enumeration='empty')).json()
        assert empty['known_empty'] is False
        empty=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(expected=0,enumeration='empty',complete=True)).json()
        assert empty['known_empty'] is True and empty['complete'] is True
        for entry in [{'id':-1},{'id':4294967296},{'id':True},{'id':'1'},{'id':1,'metadata_index':123}]:
            assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(entries=[entry])).status_code==422
        assert client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(entries=[{'id':1},{'id':1}])).status_code==422


def test_metadata_enrichment_and_byte_bounded_entry_paging_survive_restart(tmp_path):
    with client_for(tmp_path) as client:
        first=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(expected=1,enumeration='enrichment',complete=True,entries=[{'id':0}])).json()
        key=first['enumeration_key']
        enriched=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=batch(expected=1,enumeration='enrichment',entries=[{'id':0,'name':'known later'}])).json()
        assert enriched['enriched_count']==1 and enriched['observed_unique_entries']==1
        for offset in range(0,80,10):
            body=batch(expected=80,enumeration='large-chinese',complete=offset==70,entries=[{'id':number,'name':'名'*1000,'owner':'属'*1000,'display_name':'显'*1000} for number in range(offset,offset+10)])
            response=client.post('/v1/interfaces/registries/batches',headers=HEADERS,json=body)
            assert response.status_code==200,response.text
        large_key=response.json()['enumeration_key']
    with client_for(tmp_path) as client:
        seen=[]
        after=0
        while True:
            page=client.get(f'/v1/interfaces/registries/{large_key}/entries',params={'after':after,'limit':100},headers=HEADERS)
            assert len(page.content)<=512*1024
            data=page.json()
            seen.extend(entry['id'] for entry in data['entries'])
            if data['entries']:assert data['next_cursor']>after
            after=data['next_cursor']
            if not data['has_more']:break
        assert seen==list(range(80))
        small=client.get(f'/v1/interfaces/registries/{key}/entries',headers=HEADERS).json()
        assert small['entries'][0]['name']=='known later'
        assert small['enumeration']['complete'] is True
