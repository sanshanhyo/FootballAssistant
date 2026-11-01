"""Synthetic row0 hypothesis fixtures; no actual player/value or row-label ordering claim."""
import copy
import json
import unittest
from football_assistant_data.windows_goalkeeper_row_projection import (
    CONTAINER, ROW_ROOT, TITLE_PATH, LABEL_PATH, VALUE_PATH, GOALKEEPER_LABELS, project_goalkeeper_row)
from football_assistant_data.windows_discovery_import import parse_import
from test_windows_discovery_projection import fixture as position_fixture
import test_windows_discovery_import as api_fixture


def fixture():
    source, event = position_fixture()
    event['result'].update(FocusPath=CONTAINER,Reason='approved_row_targets_complete',Observations=[
        dict(Path=TITLE_PATH,Text='守\u200b门'),dict(Path=LABEL_PATH,Text='出击(倾向)'),dict(Path=VALUE_PATH,Text='1\u200b7')])
    return source,event


class RowProjectionTests(unittest.TestCase):
    def project(self,event=None,source=None):
        expected,default=fixture()
        return project_goalkeeper_row(default if event is None else event,expected_source=expected if source is None else source)
    def test_exact_paths_and_synthetic_labelled_value(self):
        self.assertEqual([len(p.split('/')) for p in (CONTAINER,TITLE_PATH,ROW_ROOT,LABEL_PATH,VALUE_PATH)],[25,26,30,39,44])
        result=self.project()
        self.assertEqual(result['fields']['displayed_attribute'],dict(category_display='守门',label_display='出击(倾向)',value_display='17',value=17,row_index=0))
        self.assertFalse(result['page_identity_verified']);self.assertFalse(result['business_identity_known'])
        self.assertIsNone(result['captured_at']);self.assertEqual(result['source_freshness'],'unknown')
        self.assertEqual(result['field_provenance']['displayed_attribute']['value_path'],VALUE_PATH)
    def test_whitelist_not_assumed_first_label(self):
        self.assertEqual(len(GOALKEEPER_LABELS),13)
        for label in GOALKEEPER_LABELS:
            source,event=fixture();event['result']['Observations'][1]['Text']=label
            self.assertEqual(self.project(event)['fields']['displayed_attribute']['label_display'],label)
    def test_bad_title_label_value_and_paths(self):
        for index,texts in ((0,['精神','守 门',' 守门','守门 ']),(1,['不存在','出击','出击（倾向）',' 出击(倾向)']),
                            (2,['0','21','017','17.0',' 17','17 ','+17','１７','<b>17</b>','1\n7','17\u200d'])):
            for text in texts:
                source,event=fixture();event['result']['Observations'][index]['Text']=text
                self.assertEqual(self.project(event)['fields'],{},repr(text))
        for index in range(3):
            source,event=fixture();event['result']['Observations'][index]['Path']+='/0'
            self.assertEqual(self.project(event)['fields'],{})
        for number in (1,20):
            source,event=fixture();event['result']['Observations'][2]['Text']=str(number)
            self.assertEqual(self.project(event)['fields']['displayed_attribute']['value'],number)
    def test_no_split_capture_duplicate_or_failed_target(self):
        source,event=fixture()
        for observations in (event['result']['Observations'][:2],event['result']['Observations'][1:],
                             event['result']['Observations']+[event['result']['Observations'][0]],
                             [event['result']['Observations'][0]]*3):
            mutated=copy.deepcopy(event);mutated['result']['Observations']=observations
            self.assertEqual(self.project(mutated)['fields'],{})
        for reason in ('bounded_raw_diagnostics','approved_prefix_exhausted','time_budget'):
            mutated=copy.deepcopy(event);mutated['result']['Reason']=reason
            self.assertEqual(self.project(mutated)['fields'],{})
    def test_source_and_nonce_mismatch(self):
        source,event=fixture()
        for key,value in [('pid',124),('entry_tid',457),('callback_tid',457),('session_id','33333333-3333-4333-8333-333333333333'),('bridge_sha256','c'*64),('game_sha256','d'*64),('page_identity_verified',True)]:
            mutated=copy.deepcopy(event);mutated[key]=value
            self.assertEqual(self.project(mutated)['fields'],{},key)
        event['result']['Request']['Nonce']='33333333-3333-4333-8333-333333333333'
        self.assertEqual(self.project(event)['fields'],{})
    def test_explicit_mode_no_guessing_or_fallback(self):
        source,event=fixture();payload=dict(capture=event,expected_source=source)
        with self.assertRaises(ValueError):parse_import(json.dumps(payload).encode(),'TEST-IMPORT-TIME')
        for mode in (None,'position','goalkeeper_row1',True):
            with self.assertRaises(ValueError):parse_import(json.dumps(dict(payload,projection_mode=mode)).encode(),'TEST')
        result=parse_import(json.dumps(dict(payload,projection_mode='goalkeeper_row0')).encode(),'TEST-IMPORT-TIME')
        self.assertEqual(result['projection']['projection_mode'],'goalkeeper_row0')
        source,event=position_fixture()
        with self.assertRaises(ValueError):parse_import(json.dumps(dict(capture=event,expected_source=source,projection_mode='goalkeeper_row0')).encode(),'TEST')


class RowImportApiTests(unittest.TestCase):
    setUp = api_fixture.ImportApiTests.setUp
    tearDown = api_fixture.ImportApiTests.tearDown
    post = api_fixture.ImportApiTests.post
    snapshot = api_fixture.ImportApiTests.snapshot
    def test_row_api_dispatch_and_failures_clear(self):
        source,event=fixture();payload=dict(capture=event,expected_source=source,projection_mode='goalkeeper_row0')
        result=self.post(payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['projection']['fields']['displayed_attribute']['value'],17)
        for mutate in ('mode','path','split','source'):
            self.assertEqual(self.post(payload).status_code,200)
            bad=copy.deepcopy(payload)
            if mutate=='mode':bad.pop('projection_mode')
            if mutate=='path':bad['capture']['result']['FocusPath']='0/6'
            if mutate=='split':bad['capture']['result']['Observations'].pop()
            if mutate=='source':bad['expected_source']['pid']+=1
            self.assertEqual(self.post(bad).status_code,422)
            self.assertIsNone(self.snapshot()['projection'])

if __name__=='__main__':unittest.main()
