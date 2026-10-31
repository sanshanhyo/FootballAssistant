"""Invented UI fixtures only: no real player identity, captures or provider calls."""
import asyncio
from copy import deepcopy
import json

import pytest

from football_assistant_agent.ui_advice import prepare_ui_advice, prepare_current_page_attributes
from football_assistant_data.current_page_attributes_projection import (
    FOCUS_ROOT, COMMON_PREFIX, LABEL_SUFFIX, VALUE_SUFFIX, CATEGORIES,
)
from test_display_profile import NOW
from test_ui_advice import snapshot


# Literal observed structure, independent of production selector constants.
PREFIX = 'focus/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0'
FIXTURE_GROUPS = {
    'goalkeeper': ('守门', '/0/0/0', '/0/0/2/0/0/0/', ('反应', '手控球')),
    'mental': ('精神', '/1/0/0', '/1/0/2/0/0/0/', ('决断', '团队合作')),
    'physical': ('身体', '/2/0/0/0', '/2/0/0/2/0/0/0/', ('爆发力', '弹跳')),
}
LABEL = '/0/0/0/0/0/0/0/0/0'
VALUE = '/0/0/0/0/0/0/1/1/0/0/0/0/0/0'


def recount(data):
    data['facts_total'] = data['source_status']['facts_count'] = len(data['facts'])


def attributes_snapshot():
    data = snapshot()
    template = deepcopy(data['facts'][0])
    values = {'focus/99': 'TEST UNRELATED PRIVATE UI'}
    for title, title_suffix, row_suffix, labels in FIXTURE_GROUPS.values():
        values[PREFIX + title_suffix] = title
        for index, label in enumerate(labels):
            values[PREFIX + row_suffix + str(index) + LABEL] = label
            values[PREFIX + row_suffix + str(index) + VALUE] = str(1 if index == 0 else 20)
    data['facts'] = [{**deepcopy(template), 'entity_id': path, 'value': value}
                     for path, value in values.items()]
    data['facts'].append(dict(entity_kind='ui_capture_diagnostic', entity_id='diagnostic/capture',
        field='capture_metrics', value=json.dumps(dict(path_scope='focus_relative',
        identity_scope='capture_local_ui_path', focus_requested=True, focus_resolved=True,
        focus_root_path='panel0/0/6'))))
    recount(data)
    return data


def row_path(category='goalkeeper', row=0, suffix=VALUE):
    return PREFIX + FIXTURE_GROUPS[category][2] + str(row) + suffix


def edit(data, path, value):
    next(f for f in data['facts'] if f['entity_id'] == path)['value'] = value


def preview(data=None):
    return prepare_current_page_attributes(data if data is not None else attributes_snapshot(), now=NOW)


def assert_unavailable(result):
    assert result['status'] != 'experimental_ui_current_page_attributes'
    projection = result.get('current_page_attributes')
    assert projection is None or not projection.get('groups')
    assert result['identity'] is None and result['individual_advice_allowed'] is False


def test_exact_observed_suffixes_and_six_synthetic_display_values():
    assert FOCUS_ROOT == 'panel0/0/6' and COMMON_PREFIX == PREFIX
    assert LABEL_SUFFIX == LABEL and VALUE_SUFFIX == VALUE
    for category, (title, title_suffix, row_suffix, _) in FIXTURE_GROUPS.items():
        assert CATEGORIES[category]['title_path'] == PREFIX + title_suffix
        assert CATEGORIES[category]['row_prefix'] == PREFIX + row_suffix
        assert CATEGORIES[category]['title'] == title
    result = preview()
    assert result['status'] == 'experimental_ui_current_page_attributes'
    assert result['identity'] is None
    assert result['individual_advice_allowed'] is False
    assert result['production_ready'] is False
    groups = result['current_page_attributes']['groups']
    assert len(groups) == 3
    for group in groups:
        category = group['category_key']
        assert group['category_display'] == FIXTURE_GROUPS[category][0]
        assert group['rows_complete'] is False
        assert [row['label_display'] for row in group['rows']] == list(FIXTURE_GROUPS[category][3])
        assert [row['value'] for row in group['rows']] == [1, 20]
        assert [row['value_display'] for row in group['rows']] == ['1', '20']
        assert all(type(row['value']) is int for row in group['rows'])
        for row in group['rows']:
            assert row['field_provenance']
    assert 'TEST UNRELATED' not in json.dumps(result)


def test_zero_width_space_is_only_normalization_and_raw_stays_local():
    data = attributes_snapshot()
    raw = '反\u200b应'
    edit(data, row_path(suffix=LABEL), raw)
    result = preview(data)
    row = result['current_page_attributes']['groups'][0]['rows'][0]
    assert row['label_display'] == '反应'
    assert raw in row['raw_texts'].values()


@pytest.mark.parametrize('value', ['0', '21', '-1', '+1', '01', '1.0', ' 1', '1 ', '１', '1/20', 'true', '\u200d1', '<b>1</b>'])
def test_bad_rating_rejects_the_entire_projection(value):
    data = attributes_snapshot(); edit(data, row_path(), value)
    assert_unavailable(preview(data))


@pytest.mark.parametrize('label', ['TEST', '反应1', '<b>反应</b>', ' 反应', '反应 ', '反\u200d应', '反\n应', '\u4dc0'])
def test_unobserved_label_normalizations_or_markup_fail_closed(label):
    data = attributes_snapshot(); edit(data, row_path(suffix=LABEL), label)
    assert_unavailable(preview(data))


@pytest.mark.parametrize('change', ['duplicate_path', 'duplicate_label', 'wrong_title', 'missing_title',
    'wrong_root', 'absolute_scope', 'build', 'platform', 'synthetic', 'stale', 'session', 'event', 'incomplete', 'later'])
def test_profile_and_fresh_session_fail_closed(change):
    data = attributes_snapshot()
    if change == 'duplicate_path': data['facts'].append(deepcopy(data['facts'][1])); recount(data)
    elif change == 'duplicate_label': edit(data, row_path(row=1, suffix=LABEL), '反应')
    elif change == 'wrong_title': edit(data, PREFIX + FIXTURE_GROUPS['mental'][1], '技术')
    elif change == 'missing_title':
        data['facts'] = [f for f in data['facts'] if f['entity_id'] != PREFIX + FIXTURE_GROUPS['mental'][1]]
        recount(data)
    elif change == 'wrong_root': data['facts'][-1]['value'] = data['facts'][-1]['value'].replace('panel0/0/6', 'panel0/0/2')
    elif change == 'absolute_scope': data['facts'][-1]['value'] = json.dumps(dict(path_scope='panel_absolute'))
    elif change == 'build':
        data['source_status']['game']['build'] = 'TEST-other'
        data['observation']['game']['build'] = 'TEST-other'
        for fact in data['facts']:
            if 'game' in fact: fact['game']['build'] = 'TEST-other'
    elif change == 'platform':
        data['observation']['source']['platform'] = 'TEST-other'
        for fact in data['facts']:
            if 'source' in fact: fact['source']['platform'] = 'TEST-other'
    elif change == 'synthetic': data['observation']['synthetic'] = True
    elif change == 'stale': data['source_status']['last_seen_at'] = '2000-01-01T00:00:00Z'
    elif change == 'session': data['observation']['game']['session_id'] = 'TEST-other'
    elif change == 'event': data['facts'][0]['source_event_id'] = 'TEST-other'
    elif change == 'incomplete': data['has_more'] = True
    elif change == 'later': data['later_source_status'] = {**data['source_status'], 'event_id': 'TEST-other'}
    assert_unavailable(preview(data))


def test_unread_pair_is_not_filled_from_neighbor_or_previous_capture():
    complete = preview()
    assert complete['status'] == 'experimental_ui_current_page_attributes'
    data = attributes_snapshot()
    data['facts'] = [f for f in data['facts'] if f['entity_id'] != row_path()]
    recount(data)
    result = preview(data)
    assert result['status'] == 'experimental_ui_current_page_attributes'
    group = result['current_page_attributes']['groups'][0]
    assert group['rows_complete'] is False
    assert [row['label_display'] for row in group['rows']] == ['手控球']
    assert [row['value'] for row in group['rows']] == [20]
    # An observed invalid value is still rejected even if its label was not read.
    data = attributes_snapshot()
    data['facts'] = [f for f in data['facts'] if f['entity_id'] != row_path(suffix=LABEL)]
    edit(data, row_path(), '99'); recount(data)
    assert_unavailable(preview(data))


def test_navigation_name_is_never_bound_across_frames_or_inside_unrelated_text():
    navigation = snapshot()
    navigation['facts'][0]['value'] = 'TEST-NAVIGATION-PLAYER-NAME'
    preview(navigation)
    data = attributes_snapshot()
    edit(data, 'focus/99', 'TEST-NAVIGATION-PLAYER-NAME')
    result = preview(data)
    assert result['identity'] is None and result['individual_advice_allowed'] is False
    assert 'TEST-NAVIGATION-PLAYER-NAME' not in json.dumps(result)


def test_default_player_ui_advice_does_not_gain_attribute_projection(monkeypatch):
    from football_assistant_agent import service
    data = attributes_snapshot()
    prepared = prepare_ui_advice('player_info', data, now=NOW)
    assert 'current_page_attributes' not in prepared
    monkeypatch.setattr(service, 'prepare_ui_advice', lambda c, s: prepare_ui_advice(c, s, now=NOW))
    captured = {}
    async def chat(message, conversation_id, context, **kwargs):
        captured.update(context=context)
        return {'reply': 'TEST non-personal conditional response'}
    agent = service.AgentService(None, None)
    monkeypatch.setattr(agent, '_chat', chat)
    result = asyncio.run(agent.ui_advice('TEST', None, 'player_info', data))
    assert result['status'] == 'generated'
    assert 'current_page_attributes' not in captured['context']['ui_evidence']
    assert 'experimental_ui_current_page_attributes' not in json.dumps(captured)


def test_authenticated_reader_preview_is_model_free_and_has_no_raw_fallback(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from football_assistant_data.app import create_app
    from football_assistant_agent import ui_advice
    from test_reader import settings, AUTH
    monkeypatch.setattr(ui_advice, 'prepare_current_page_attributes',
        lambda data: prepare_current_page_attributes(data, now=NOW))
    app = create_app(settings(tmp_path), enable_agent=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.get('/v1/reader/current-page-attributes').status_code == 401
        result = client.get('/v1/reader/current-page-attributes', headers=AUTH).json()
        assert_unavailable(result)
        monkeypatch.setattr(app.state.observations, 'reader_snapshot', lambda *args: attributes_snapshot())
        result = client.get('/v1/reader/current-page-attributes', headers=AUTH).json()
        assert result['status'] == 'experimental_ui_current_page_attributes'
        assert result['identity'] is None and result['individual_advice_allowed'] is False
        assert 'TEST UNRELATED' not in json.dumps(result)
        assert 'evidence' not in result


def test_preview_uses_full_validated_capture_not_model_evidence_prefix():
    data = attributes_snapshot()
    template = deepcopy(data['facts'][0])
    noise = [{**deepcopy(template), 'entity_id': f'focus/98/{index}',
              'value': 'TEST PRIVATE PREFIX ' + ('x' * 900)} for index in range(25)]
    data['facts'] = noise + data['facts']
    recount(data)
    prepared = prepare_ui_advice('player_info', data, now=NOW)
    assert prepared['evidence_truncated'] is True
    result = preview(data)
    assert result['status'] == 'experimental_ui_current_page_attributes'
    assert sum(len(group['rows']) for group in result['current_page_attributes']['groups']) == 6
    assert 'TEST PRIVATE PREFIX' not in json.dumps(result)


@pytest.mark.parametrize('bad_index', ['00', '-1', '32', '511', 'wrong'])
def test_unsupported_row_coordinates_fail_closed(bad_index):
    data = attributes_snapshot()
    fact = next(f for f in data['facts'] if f['entity_id'] == row_path())
    fact['entity_id'] = PREFIX + FIXTURE_GROUPS['goalkeeper'][2] + bad_index + VALUE
    assert_unavailable(preview(data))


def test_projection_digest_changes_with_current_values_without_identity_binding():
    data = attributes_snapshot()
    original = preview(data)['current_page_attributes']['projection_sha256']
    edit(data, row_path(), '7')
    result = preview(data)
    assert result['current_page_attributes']['projection_sha256'] != original
    assert result['identity'] is None


@pytest.mark.parametrize('label', ['出击(倾向)', '拳击球(倾向)'])
def test_confirmed_goalkeeper_parentheses_labels_preserve_exact_display(label):
    data = attributes_snapshot()
    raw = label[0] + '\u200b' + label[1:]
    edit(data, row_path(suffix=LABEL), raw)
    result = preview(data)
    row = result['current_page_attributes']['groups'][0]['rows'][0]
    assert row['label_display'] == label
    assert row['raw_texts']['label_display'] == raw
    assert result['identity'] is None


@pytest.mark.parametrize('label', ['出击（倾向）', '拳击球（倾向）', '出击', '未知属性', '决断'])
def test_unconfirmed_or_wrong_category_labels_fail_closed(label):
    data = attributes_snapshot(); edit(data, row_path(suffix=LABEL), label)
    assert_unavailable(preview(data))


def test_confirmed_zero_width_category_titles_match_without_other_normalization():
    data = attributes_snapshot()
    for title, title_suffix, _, _ in FIXTURE_GROUPS.values():
        edit(data, PREFIX + title_suffix, title[0] + '\u200b' + title[1:])
    result = preview(data)
    assert [g['category_display'] for g in result['current_page_attributes']['groups']] == ['守门', '精神', '身体']
    assert all('\u200b' in g['raw_title'] for g in result['current_page_attributes']['groups'])


def test_all_confirmed_labels_are_display_only_and_never_assert_complete_coverage():
    confirmed = {
        'goalkeeper': ('出击(倾向)', '传球', '大脚开球', '反应', '拦截传中', '拳击球(倾向)', '手控球', '手抛球', '停球', '一对一', '意外性', '指挥防守', '制空范围'),
        'mental': ('才华', '防守站位', '工作投入', '集中', '决断', '领导力', '侵略性', '视野', '团队合作', '无球跑动', '意志力', '勇敢', '预判', '镇定'),
        'physical': ('爆发力', '弹跳', '灵活', '耐力', '平衡', '强壮', '速度', '体质'),
    }
    data = attributes_snapshot()
    data['facts'] = [f for f in data['facts'] if not any(
        f['entity_id'].startswith(PREFIX + group[2]) for group in FIXTURE_GROUPS.values())]
    template = deepcopy(data['facts'][0])
    for category, labels in confirmed.items():
        for index, label in enumerate(labels):
            for suffix, value in ((LABEL, label), (VALUE, str(index % 20 + 1))):
                data['facts'].append({**deepcopy(template), 'entity_id': row_path(category, index, suffix), 'value': value})
    recount(data)
    result = preview(data)
    assert result['status'] == 'experimental_ui_current_page_attributes'
    for group in result['current_page_attributes']['groups']:
        assert tuple(row['label_display'] for row in group['rows']) == confirmed[group['category_key']]
        assert group['rows_complete'] is False
        assert all('attribute_id' not in row for row in group['rows'])
    assert result['current_page_attributes']['missing_rows_unknown'] is True
    assert result['identity'] is None and result['individual_advice_allowed'] is False
