"""Synthetic scope metadata; not game samples or semantic row associations."""
from copy import deepcopy
import json

import pytest

from football_assistant_agent.ui_advice import prepare_ui_advice
from football_assistant_data.ui_capture_scope import capture_path_scope
from test_ui_advice import snapshot
from test_display_profile import sample, project, NOW


def scoped_snapshot(root='panel0/0/1'):
    data = snapshot()
    for i, fact in enumerate(data['facts']):
        fact['entity_id'] = f'focus/{i}'
    metrics = dict(path_scope='focus_relative', identity_scope='capture_local_ui_path',
                   focus_requested=True, focus_resolved=True, focus_root_path=root,
                   extra_untrusted_note='TEST NEVER FORWARD DIAGNOSTIC INSTRUCTIONS')
    data['facts'].append(dict(entity_kind='ui_capture_diagnostic', entity_id='diagnostic/capture',
                              field='capture_metrics', value=json.dumps(metrics)))
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])
    return data


def test_focused_evidence_has_explicit_capture_local_root_provenance_not_raw_diagnostics():
    data = scoped_snapshot()
    result = prepare_ui_advice('schedule_analysis', data, now=NOW)
    assert result['status'] == 'ready'
    assert result['provenance']['path_scope'] == 'focus_relative'
    assert result['provenance']['focus_root_path'] == 'panel0/0/1'
    assert result['provenance']['identity_scope'] == 'capture_local_ui_path'
    assert 'TEST NEVER FORWARD' not in str(result)
    assert all(f['path'].startswith('focus/') for f in result['evidence'])
    other = prepare_ui_advice('schedule_analysis', scoped_snapshot('panel0/0/2'), now=NOW)
    assert result['evidence'] == other['evidence']
    assert result['capture_text_sha256'] != other['capture_text_sha256']


@pytest.mark.parametrize('change', [
    lambda m: m.update(path_scope='unknown'),
    lambda m: m.update(focus_root_path='panel0/00'),
    lambda m: m.update(focus_root_path='panel32'),
    lambda m: m.update(focus_root_path='panel0/512'),
    lambda m: m.update(focus_root_path='panel0/' + '1' * 128),
    lambda m: m.update(focus_root_path='TEST instructions'),
    lambda m: m.update(focus_requested=False),
    lambda m: m.update(focus_requested=1),
    lambda m: m.update(focus_resolved=False),
    lambda m: m.update(identity_scope='stable_player_id'),
    lambda m: m.pop('focus_root_path'),
])
def test_malformed_focus_scope_fails_closed(change):
    data = scoped_snapshot()
    metrics = json.loads(data['facts'][-1]['value'])
    change(metrics)
    data['facts'][-1]['value'] = json.dumps(metrics)
    result = prepare_ui_advice('schedule_analysis', data, now=NOW)
    assert result['status'] == 'blocked' and result['evidence'] == []
    assert result['reasons'] == ['invalid_ui_capture_scope']


@pytest.mark.parametrize('value', ['not JSON', '[]', 'null', '{"path_scope":"panel_absolute","path_scope":"focus_relative"}', '{"number":NaN}', '[' * 2000])
def test_malformed_capture_diagnostic_json_fails_closed(value):
    data = scoped_snapshot()
    data['facts'][-1]['value'] = value
    assert prepare_ui_advice('player_info', data, now=NOW)['status'] == 'blocked'


@pytest.mark.parametrize('path', ['panel0/0', 'focus/00', 'focus/512', 'focus/' + '1' * 128])
def test_mixed_or_invalid_relative_paths_fail_closed(path):
    data = scoped_snapshot()
    data['facts'][0]['entity_id'] = path
    assert prepare_ui_advice('player_info', data, now=NOW)['status'] == 'blocked'


def test_scope_required_for_relative_paths_and_capture_diagnostics_unique():
    data = scoped_snapshot()
    data['facts'].pop()
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])
    assert prepare_ui_advice('player_info', data, now=NOW)['status'] == 'blocked'
    data = scoped_snapshot()
    data['facts'].append(deepcopy(data['facts'][-1]))
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])
    assert prepare_ui_advice('player_info', data, now=NOW)['status'] == 'blocked'
    data = scoped_snapshot()
    data['facts'][-1]['source_event_id'] = 'TEST wrong root provenance'
    assert prepare_ui_advice('player_info', data, now=NOW)['status'] == 'blocked'


def test_profile_rejects_relative_scope_even_with_old_matching_selectors():
    data = sample()
    data['facts'].append(scoped_snapshot()['facts'][-1])
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])
    result = project(data)
    assert result['status'] == 'unavailable' and result['reason'] == 'unsupported_layout'
    assert result['fields'] == {}


def test_legacy_without_scope_metadata_defaults_to_panel_paths():
    assert capture_path_scope([]) == dict(path_scope='panel_absolute', focus_root_path=None,
                                         identity_scope='capture_local_ui_path')
    result = prepare_ui_advice('player_info', snapshot(), now=NOW)
    assert result['status'] == 'ready' and result['provenance']['path_scope'] == 'panel_absolute'
