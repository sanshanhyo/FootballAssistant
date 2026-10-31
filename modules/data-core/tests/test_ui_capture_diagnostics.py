"""Synthetic traversal diagnostics only; no game samples or native execution."""
import json
import pytest
from pathlib import Path

from football_assistant_contracts.validation import validate_observation
from football_assistant_data.reader_cli import arguments
from football_assistant_data.reader_client import ReaderError
from test_backend import client_for, settings, AUTH


def diagnostic_fixture():
    root = Path(__file__).resolve().parents[3]
    body = json.loads((root / 'contracts/examples/synthetic-fact-snapshot.json').read_text(encoding="utf-8"))
    body['status'] = 'partial'
    body['source']['adapter_id'] = 'footballassistant.runtime-ui-tree'
    body['source']['adapter_version'] = '0.4.0'
    body['payload']['facts'] = [dict(entity_kind='ui_element', entity_id=f'panel0/{i}',
                                   field='ui_tree_text', value=f'TEST text {i}') for i in range(240)]
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
        response = client.get('/v1/reader/snapshot?limit=274', headers=AUTH)
        assert response.status_code == 200
        assert client.get('/v1/reader/snapshot?limit=275', headers=AUTH).status_code == 422
        snapshot = response.json()
        assert snapshot['facts_total'] == 274 and snapshot['has_more'] is False
        assert sum(f['entity_kind'] == 'ui_element' for f in snapshot['facts']) == 240
        assert sum(f['entity_kind'] == 'ui_capture_diagnostic' for f in snapshot['facts']) == 34


def test_cli_capture_bound_matches_snapshot_api():
    assert arguments('snapshot', ['--limit', '274']).limit == 274
    assert arguments('raw-ui', ['--limit', '274']).limit == 274
    with pytest.raises(ReaderError):
        arguments('snapshot', ['--limit', '275'])
    with pytest.raises(ReaderError):
        arguments('native', ['--limit', '101'])
