"""Synthetic contract tests only: no native capture or football evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from football_assistant_data.business_snapshot import (
    BusinessSnapshot, TECHNICAL, MENTAL, PHYSICAL, assess_business_snapshot,
)

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def sample():
    return {'source': {'kind': 'test_fixture', 'adapter_id': 'synthetic-test',
            'adapter_version': 'test-1', 'session_id': 'test-session', 'game_build': 'TEST-build',
            'game_assembly_sha256': 'a'*64, 'metadata_sha256': 'b'*64, 'game_plugin_sha256':'c'*64,
            'mapper_version': 'test-only', 'evidence_ref': 'synthetic fixture only',
            'captured_at': NOW, 'observed_at': NOW, 'synthetic': True,
            'identity_scope': 'test-player-ids-v1'}, 'snapshot_id': 'test-snapshot',
            'managed_team_id': 'test-team', 'roster_complete': True,
            'teams': [{'id': 'test-team', 'name': 'Synthetic team'}],
            'players': [{'id': 'test-player', 'name': 'Synthetic player', 'team_id': 'test-team',
                         'age': 20, 'positions': ['ST'], 'fitness_percent': 100.0,
                         'injured': False, 'suspended': False,
                         'attributes': {name: {key: 10 for key in keys} for name, keys in
                                        [('technical',TECHNICAL), ('mental',MENTAL), ('physical',PHYSICAL)]}}]}


def validate(data):
    return BusinessSnapshot.model_validate(data)


def test_no_data_never_ready():
    result = assess_business_snapshot(None, now=NOW)
    assert result['source'] is None
    assert result['status'] == 'unavailable'
    assert 'no_business_snapshot' in result['reasons']
    assert not result['production_ready']
    assert all(not c['ready'] for c in result['capabilities'].values())


def test_complete_synthetic_player_still_not_production():
    result = assess_business_snapshot(validate(sample()), now=NOW)
    assert result['capabilities']['player_info']['missing_requirements'] == []
    assert result['capabilities']['player_info']['ready'] is False
    assert {'synthetic_data', 'not_native_read', 'native_producer_not_verified'} <= set(result['reasons'])
    assert 'candidate_ids' in result['capabilities']['transfer_analysis']['missing_requirements']
    assert 'tactic.formation' in result['capabilities']['tactical_analysis']['missing_requirements']
    assert 'world_date' in result['capabilities']['schedule_analysis']['missing_requirements']


def test_claimed_native_source_cannot_self_certify():
    data = sample()
    data['source'].update(kind='native_read', synthetic=False)
    result = assess_business_snapshot(validate(data), now=NOW)
    assert result['reasons'] == ['native_producer_not_verified']
    assert not result['production_ready']
    assert all(not c['ready'] for c in result['capabilities'].values())


@pytest.mark.parametrize('kind', ['ui', 'save', 'registry', 'runtime', 'verified_native'])
def test_unapproved_source_kinds_rejected(kind):
    data = sample(); data['source']['kind'] = kind
    with pytest.raises(ValidationError): validate(data)


def test_fixture_false_flag_rejected():
    data = sample(); data['source']['synthetic'] = False
    with pytest.raises(ValidationError): validate(data)


@pytest.mark.parametrize('field,value', [('age', True), ('age','20'), ('age', -1),
    ('fitness_percent', float('nan')), ('fitness_percent',101.0), ('injured','false'),
    ('id','pointer / path'), ('name','')])
def test_player_strict_types(field, value):
    data = sample(); data['players'][0][field] = value
    with pytest.raises(ValidationError): validate(data)


@pytest.mark.parametrize('rating', [0,21,True,'10'])
def test_attribute_range(rating):
    data = sample(); data['players'][0]['attributes']['technical']['passing'] = rating
    with pytest.raises(ValidationError): validate(data)


def test_unknown_field_and_unknown_attribute_rejected():
    data = sample(); data['production_ready'] = True
    with pytest.raises(ValidationError): validate(data)
    data = sample(); data['players'][0]['attributes']['mental']['hidden_potential'] = 20
    with pytest.raises(ValidationError): validate(data)


def test_unknown_is_not_zero_false_or_empty():
    data = sample(); data['players'][0]['injured'] = None
    data['players'][0]['fitness_percent'] = 0.0
    data['players'][0]['attributes']['physical'] = {}
    result = assess_business_snapshot(validate(data), now=NOW)
    missing = result['capabilities']['player_info']['missing_requirements']
    assert 'player.injured' in missing
    assert 'player.fitness_percent' not in missing
    assert 'player.suspended' not in missing
    assert 'player.attributes.physical' in missing


@pytest.mark.parametrize('collection', ['players','teams'])
def test_duplicate_identity_rejected(collection):
    data = sample(); data[collection].append(deepcopy(data[collection][0]))
    with pytest.raises(ValidationError): validate(data)


@pytest.mark.parametrize('change', ['unknown_candidate','unknown_contract','scope','absent_collection'])
def test_identity_and_completeness(change):
    data = sample()
    if change == 'unknown_candidate': data['candidate_ids'] = ['unknown']
    elif change == 'unknown_contract': data['contracts'] = [{'player_id':'unknown'}]
    elif change == 'scope': data['managed_team_id'] = None
    else: data['players'] = None
    with pytest.raises(ValidationError): validate(data)


@pytest.mark.parametrize('field,delta,reason', [('observed_at',-16,'observation_not_fresh'),
    ('captured_at',-16,'capture_not_fresh'), ('captured_at',1,'capture_not_fresh'),
    ('observed_at',1,'observation_not_fresh')])
def test_independent_freshness(field, delta, reason):
    data = sample(); data['source'][field] = NOW + timedelta(seconds=delta)
    assert reason in assess_business_snapshot(validate(data), now=NOW)['reasons']


def test_unknown_and_naive_time():
    data = sample(); data['source']['observed_at'] = None
    assert 'observation_time_unknown' in assess_business_snapshot(validate(data),now=NOW)['reasons']
    data['source']['captured_at'] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError): validate(data)


@pytest.mark.parametrize('bound', [0,16,float('nan'),True])
def test_freshness_cannot_be_disabled(bound):
    with pytest.raises(ValueError): assess_business_snapshot(None,now=NOW,max_age_seconds=bound)


def test_money_semantics_and_fixture_identity():
    data = sample()
    data['contracts'] = [{'player_id':'test-player', 'wage': {'money': {
        'amount_minor':100, 'currency':'GBP', 'minor_unit_exponent':2}, 'period':'week'}}]
    parsed = validate(data)
    assert parsed.contracts[0].wage.money.amount_minor == 100
    data['contracts'][0]['wage']['period'] = 'unknown'
    with pytest.raises(ValidationError): validate(data)
    data = sample(); data['fixtures'] = [{'id':'f','home_team_id':'t','away_team_id':'t','date':'2026-10-30'}]
    with pytest.raises(ValidationError): validate(data)


def test_json_roundtrip_and_tactic_identity():
    model = validate(sample())
    assert BusinessSnapshot.model_validate_json(model.model_dump_json()) == model
    data = sample(); data['tactics'] = [{'team_id':'test-team','formation':'4-4-2',
        'instructions': [], 'lineup':[{'player_id':'unknown','position':'ST','role':'forward','duty':'attack','instructions':[]}]}]
    missing = assess_business_snapshot(validate(data),now=NOW)['capabilities']['tactical_analysis']['missing_requirements']
    assert 'tactic.lineup_identity' in missing
    data['tactics'][0]['lineup'] *= 2
    with pytest.raises(ValidationError): validate(data)


def test_all_domains_structurally_complete_never_claims_live_success():
    data = sample()
    money = {'amount_minor':100, 'currency':'GBP', 'minor_unit_exponent':2}
    wage = {'money':money, 'period':'week'}
    data.update(world_date='2026-10-30', world_local_time='12:00:00', world_time_basis='game_local', candidate_ids=['test-player'],
        candidates_complete=True, candidate_scope='synthetic specified shortlist',
        contracts=[{'player_id':'test-player','wage':wage,'expires_on':'2027-06-30','asking_price':money}],
        finances=[{'team_id':'test-team','transfer_budget':money,'wage_room':wage}],
        fixtures_complete=True, fixture_window_start='2026-10-30', fixture_window_end='2026-11-30',
        fixtures=[], tactics=[{'team_id':'test-team','formation':'test-formation','instructions':[],
            'lineup':[{'player_id':'test-player','position':'ST','role':'test-role','duty':'test-duty','instructions':[]}]}])
    result = assess_business_snapshot(validate(data),now=NOW)
    assert all(c['missing_requirements'] == [] and c['ready'] is False for c in result['capabilities'].values())
    assert result['production_ready'] is False
    assert 'native_producer_not_verified' in result['reasons']


def test_bounded_schedule_scope_and_reversed_window():
    data = sample(); data.update(fixtures_complete=True,fixtures=[],world_date='2026-10-30')
    result = assess_business_snapshot(validate(data),now=NOW)
    assert 'complete_fixture_scope' in result['capabilities']['schedule_analysis']['missing_requirements']
    data.update(fixture_window_start='2026-11-01',fixture_window_end='2026-10-01')
    with pytest.raises(ValidationError): validate(data)


def test_positive_availability_needs_detail():
    data = sample(); data['players'][0].update(injured=True,suspended=True)
    missing = assess_business_snapshot(validate(data),now=NOW)['capabilities']['player_info']['missing_requirements']
    assert {'player.injury_detail','player.suspension_detail'} <= set(missing)


def test_negative_wage_room_but_nonnegative_contract_wage():
    data = sample()
    money = {'amount_minor':-100,'currency':'GBP','minor_unit_exponent':2}
    data['finances'] = [{'team_id':'test-team','wage_room':{'money':money,'period':'week'}}]
    assert validate(data).finances[0].wage_room.money.amount_minor == -100
    data['contracts'] = [{'player_id':'test-player','wage':{'money':money,'period':'week'}}]
    with pytest.raises(ValidationError): validate(data)


def test_schedule_time_is_unknown_and_independent_of_player_attributes():
    data = sample(); data['players'][0]['attributes'] = None
    data.update(world_date='2026-10-30',fixtures_complete=True,
                fixture_window_start='2026-10-30',fixture_window_end='2026-11-30',fixtures=[{
                    'id':'f','home_team_id':'test-team','away_team_id':'opponent','date':'2026-11-01'}])
    schedule = assess_business_snapshot(validate(data),now=NOW)['capabilities']['schedule_analysis']
    assert {'world_local_time','world_time_basis','fixture.local_time','fixture.time_basis'} <= set(schedule['missing_requirements'])
    assert 'player.attributes.technical' not in schedule['missing_requirements']
    assert 'player.attributes.technical' in schedule['missing_rotation_requirements']
    assert schedule['scope'] == 'basic_fixture_congestion'


def test_native_plugin_identity_missing_remains_explicit():
    data = sample(); data['source'].update(kind='native_read',synthetic=False,game_plugin_sha256=None)
    assert 'native_game_plugin_identity_unknown' in assess_business_snapshot(validate(data),now=NOW)['reasons']
