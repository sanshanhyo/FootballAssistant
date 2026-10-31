"""Synthetic traversal diagnostics only; no game samples or native execution."""
import json
from pathlib import Path

from football_assistant_contracts.validation import validate_observation
from test_backend import client_for, settings, AUTH


def diagnostic_fixture():
    root = Path(__file__).resolve().parents[3]
    body = json.loads((root / 'contracts/examples/synthetic-fact-snapshot.json').read_text())
    body['status'] = 'partial'
    body['source']['adapter_id'] = 'footballassistant.runtime-ui-tree'
    body['source']['adapter_version'] = '0.4.0'
    body['payload']['facts'] = [dict(entity_kind='ui_element', entity_id=f'panel0/{i}',
                                   field='ui_tree_text', value=f'TEST text {i}') for i in range(80)]
    for name in ['capture', *[f'panel{i}' for i in range(32)], 'transport']:
        body['payload']['facts'].append(dict(entity_kind='ui_capture_diagnostic',
            entity_id=f'diagnostic/{name}', field='capture_metrics',
            value=json.dumps(dict(visited_nodes=10, elapsed_ms=1.2, stop_reason='time_budget', truncated=True))))
    return body


def test_synthetic_diagnostics_preserve_scalar_schema_and_backend_snapshot(tmp_path):
    body = diagnostic_fixture()
    assert body['synthetic'] is True
    validate_observation(body)
    with client_for(settings(tmp_path)) as client:
        assert client.post('/v1/observations', headers=AUTH, json=body).status_code == 200
        response = client.get('/v1/reader/snapshot?limit=114', headers=AUTH)
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot['facts_total'] == 114 and snapshot['has_more'] is False
        assert sum(f['entity_kind'] == 'ui_element' for f in snapshot['facts']) == 80
        assert sum(f['entity_kind'] == 'ui_capture_diagnostic' for f in snapshot['facts']) == 34
