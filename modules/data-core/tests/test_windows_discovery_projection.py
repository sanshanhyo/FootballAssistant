import copy
import unittest
from football_assistant_data.windows_discovery_projection import (GAME_SHA256, CONTAINER, LABEL_PATH, VALUE_PATH,
                              normalize_display_text, project_position_display)


def fixture():
    source = dict(pid=123, entry_tid=456, session_id="11111111-1111-4111-8111-111111111111",
                  bridge_sha256="a"*64, game_sha256=GAME_SHA256)
    nonce = "22222222-2222-4222-8222-222222222222"
    event = dict(source, phase="single_shot_raw_discovery_result", callback_tid=456, nonce=nonce,
                 page_identity_verified=False, business_facts=False, terminal=True,
                 result=dict(Status="raw_diagnostics", Reason="bounded_raw_diagnostics",
                             PageIdentityVerified=False, PanelIndex=0, FocusPath="0/6",
                             Request=dict(SchemaVersion=3, Nonce=nonce, ApprovalSha256="b"*64),
                             Observations=[dict(Path=LABEL_PATH, Text="位\u200b置"),
                                           dict(Path=VALUE_PATH, Text="TEST-\u200bPOSITION"),
                                           dict(Path=CONTAINER.rsplit('/',1)[0]+"/1/0/3", Text="比\u200b较")]))
    return source, event


class ProjectionTests(unittest.TestCase):
    def project(self, event=None, source=None, **kwargs):
        expected, default = fixture()
        return project_position_display(default if event is None else event,
                                        expected_source=expected if source is None else source, **kwargs)
    def denied(self, event, reason=None):
        result = self.project(event)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["fields"], {})
        self.assertIsNone(result["entity_id"])
        if reason: self.assertEqual(result["reason"], reason)
    def test_same_event_position_display_only(self):
        result = self.project()
        self.assertEqual(result["fields"], {"displayed_position": "TEST-POSITION"})
        self.assertEqual(result["status"], "partial_display_state")
        self.assertTrue(result["source_identity_unverified"])
        self.assertFalse(result["page_identity_verified"])
        self.assertFalse(result["business_identity_known"])
        self.assertFalse(result["snapshot_atomic"])
        self.assertEqual(result["source_freshness"], "unknown")
        self.assertIsNone(result["captured_at"])
    def test_topology_depth_and_asymmetric_tails(self):
        self.assertEqual(len(CONTAINER.split('/')),22)
        self.assertEqual(len(LABEL_PATH.split('/')),23)
        self.assertEqual(len(VALUE_PATH.split('/')),25)
        self.assertEqual(LABEL_PATH, CONTAINER+'/0')
        self.assertEqual(VALUE_PATH, CONTAINER+'/1/0/0')
    def test_no_prior_capture_cache_or_cross_event_join(self):
        _, event = fixture()
        self.assertEqual(self.project(event)["status"], "partial_display_state")
        event["result"]["Observations"] = event["result"]["Observations"][:1]
        self.denied(event,"missing_label_or_value")
        _, other = fixture(); other["result"]["Observations"] = other["result"]["Observations"][1:]
        self.denied(other,"missing_label_or_value")
    def test_reversed_label_value_and_neighbor_not_accepted(self):
        _, event = fixture()
        event["result"]["Observations"][0]["Text"] = "TEST-POSITION"
        self.denied(event,"label_mismatch")
        _, event = fixture(); event["result"]["Observations"][1]["Path"] += '/0'
        self.denied(event,"missing_label_or_value")
    def test_duplicates_even_equal_fail(self):
        _, event = fixture(); event["result"]["Observations"].append(copy.deepcopy(event["result"]["Observations"][0]))
        self.denied(event,"duplicate_path")
    def test_source_binding_mutations(self):
        for key,value in dict(pid=124,entry_tid=457,callback_tid=457,session_id="33333333-3333-4333-8333-333333333333",
                              bridge_sha256="c"*64,game_sha256="d"*64).items():
            with self.subTest(key=key):
                _, event = fixture(); event[key]=value; self.denied(event,"source_mismatch")
    def test_nonce_schema_and_safety_failure(self):
        for key,value in (("Nonce","33333333-3333-4333-8333-333333333333"),("SchemaVersion",1),("SchemaVersion",True)):
            _,event=fixture();event['result']['Request'][key]=value;self.denied(event,"event_mismatch")
        for key,value in (("Status","terminal_failure"),("PageIdentityVerified",True),("PanelIndex",1),("PanelIndex",False),("FocusPath","0/7")):
            _,event=fixture();event['result'][key]=value;self.denied(event,"unsupported_capture")
    def test_known_build_only(self):
        source,event=fixture();source['game_sha256']='c'*64;event['game_sha256']='c'*64
        self.assertEqual(self.project(event,source)['reason'],'unsupported_build')
    def test_manual_context_does_not_become_name_or_identity(self):
        result=self.project(operator_context="TEST operator page A")
        self.assertEqual(result['operator_context']['text'],"TEST operator page A")
        self.assertFalse(result['operator_context']['bridge_verified'])
        self.assertFalse(result['operator_context']['used_for_identity'])
        self.assertNotIn('name',result['fields']); self.assertIsNone(result['entity_id'])
    def test_manual_context_cannot_rescue_missing_field(self):
        _,event=fixture();event['result']['Observations']=[]
        result=self.project(event,operator_context="TEST operator page A")
        self.assertEqual(result['fields'],{});self.assertIsNone(result['operator_context'])
    def test_complete_prefix_still_not_full_profile(self):
        _,event=fixture();event['result']['Reason']='approved_prefix_exhausted'
        result=self.project(event);self.assertTrue(result['partial']);self.assertFalse(result['business_identity_known'])
    def test_observation_caps_and_paths(self):
        for path in ('0/7/0','0/6/00','0/6/8','0/6/511','0/6/512','0/6/'+('/'.join(['0']*31))):
            _,event=fixture();event['result']['Observations'][2]['Path']=path;self.denied(event,'invalid_path')
        _,event=fixture();event['result']['Observations']*=3;self.denied(event,'invalid_observations')
    def test_normalizer_specific_not_general_unicode_folding(self):
        self.assertEqual(normalize_display_text(' 位\u200b置 '),'位置')
        self.assertEqual(normalize_display_text('ＴＥＳＴ'),'ＴＥＳＴ')
        for text in ('','\u200b','TEST\u200c','TEST\u200d','TEST\ufeff','TEST\u202e','TEST\n','TEST\ud800','<color=red>TEST</color>','x'*129,'😀'*65):
            with self.subTest(text=repr(text)):
                with self.assertRaises(ValueError): normalize_display_text(text)
        self.assertEqual(normalize_display_text('😀'*64),'😀'*64)
    def test_invalid_input_failclosed(self):
        for value in (None, [], 'TEST'):
            self.assertEqual(project_position_display(value,expected_source={})['fields'],{})

if __name__=='__main__': unittest.main()
