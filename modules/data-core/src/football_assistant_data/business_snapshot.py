"""Consumer contract, not a native reader or an assertion of verified game data.

No production producer is registered. Payload claims never grant readiness.
Missing values are unknown; explicit empty lists mean observed empty only within
this snapshot's declared collection scope. No UI/save/registry coercion occurs.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:+-]+$")]
Label = Annotated[str, Field(min_length=1, max_length=256)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Rating = Annotated[int, Field(ge=1, le=20)]
LocalTime = Annotated[str, Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$')]
TimeBasis = Literal['game_local', 'utc']
TECHNICAL = frozenset('corners crossing dribbling finishing first_touch free_kick_taking heading long_shots long_throws marking passing penalty_taking tackling technique'.split())
MENTAL = frozenset('aggression anticipation bravery composure concentration decisions determination flair leadership off_the_ball positioning teamwork vision work_rate'.split())
PHYSICAL = frozenset('acceleration agility balance jumping_reach natural_fitness pace stamina strength'.split())


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class BusinessSource(Record):
    kind: Literal['native_read', 'test_fixture', 'unverified']
    adapter_id: Identifier
    adapter_version: Identifier
    session_id: Identifier
    game_build: Label
    game_assembly_sha256: Digest
    metadata_sha256: Digest
    game_plugin_sha256: Digest | None = None
    mapper_version: Identifier
    evidence_ref: Label
    captured_at: datetime = Field(strict=False)
    observed_at: datetime | None = Field(default=None, strict=False)
    synthetic: bool
    # A namespace/version, never an address, channel key or UI path.
    identity_scope: Identifier

    @model_validator(mode='after')
    def source_rules(self):
        for timestamp in (self.captured_at, self.observed_at):
            if timestamp is not None and timestamp.utcoffset() is None:
                raise ValueError('timestamps require timezone')
        if self.kind == 'test_fixture' and not self.synthetic:
            raise ValueError('test fixtures must be synthetic')
        return self


class PlayerAttributes(Record):
    technical: dict[str, Rating] | None = None
    mental: dict[str, Rating] | None = None
    physical: dict[str, Rating] | None = None

    @field_validator('technical', 'mental', 'physical')
    @classmethod
    def known_attributes(cls, value, info):
        allowed = {'technical': TECHNICAL, 'mental': MENTAL, 'physical': PHYSICAL}[info.field_name]
        if value is not None and not value.keys() <= allowed:
            raise ValueError('unsupported attribute name')
        return value


class Player(Record):
    id: Identifier
    name: Label | None = None
    team_id: Identifier | None = None
    age: Annotated[int, Field(ge=0, le=100)] | None = None
    positions: Annotated[list[Label], Field(max_length=32)] | None = None
    attributes: PlayerAttributes | None = None
    fitness_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    injured: bool | None = None
    injury_detail: Label | None = None
    suspended: bool | None = None
    suspension_detail: Label | None = None


class Team(Record):
    id: Identifier
    name: Label | None = None


class Money(Record):
    amount_minor: Annotated[int, Field(ge=0, le=9_000_000_000_000_000)]
    currency: Annotated[str, Field(pattern=r'^[A-Z]{3}$')]
    minor_unit_exponent: Annotated[int, Field(ge=0, le=4)]


class Wage(Record):
    money: Money
    period: Literal['week', 'month', 'year']


class SignedMoney(Money):
    amount_minor: Annotated[int, Field(ge=-9_000_000_000_000_000, le=9_000_000_000_000_000)]


class WageRoom(Record):
    money: SignedMoney
    period: Literal['week', 'month', 'year']


class Contract(Record):
    player_id: Identifier
    wage: Wage | None = None
    expires_on: Date | None = Field(default=None, strict=False)
    asking_price: Money | None = None
    estimated_value: Money | None = None


class ClubFinance(Record):
    team_id: Identifier
    transfer_budget: Money | None = None
    wage_room: WageRoom | None = None


class Fixture(Record):
    id: Identifier
    home_team_id: Identifier
    away_team_id: Identifier
    date: Date = Field(strict=False)
    local_time: LocalTime | None = None
    time_basis: TimeBasis | None = None
    competition_id: Identifier | None = None
    competition_name: Label | None = None

    @model_validator(mode='after')
    def opponents_differ(self):
        if self.home_team_id == self.away_team_id:
            raise ValueError('fixture opponents must differ')
        return self


class LineupSlot(Record):
    player_id: Identifier
    position: Label
    role: Label | None = None
    duty: Label | None = None
    instructions: Annotated[list[Label], Field(max_length=64)] | None = None


class Tactic(Record):
    team_id: Identifier
    formation: Label | None = None
    lineup: Annotated[list[LineupSlot], Field(max_length=32)] | None = None
    instructions: Annotated[list[Label], Field(max_length=128)] | None = None

    @model_validator(mode='after')
    def unique_players(self):
        if self.lineup is not None and len({p.player_id for p in self.lineup}) != len(self.lineup):
            raise ValueError('duplicate lineup player')
        return self


class BusinessSnapshot(Record):
    schema_version: Literal['business-snapshot/0.1'] = 'business-snapshot/0.1'
    source: BusinessSource
    snapshot_id: Identifier
    world_date: Date | None = Field(default=None, strict=False)
    world_local_time: LocalTime | None = None
    world_time_basis: TimeBasis | None = None
    managed_team_id: Identifier | None = None
    roster_complete: bool = False
    candidates_complete: bool = False
    candidate_scope: Label | None = None
    fixtures_complete: bool = False
    fixture_window_start: Date | None = Field(default=None, strict=False)
    fixture_window_end: Date | None = Field(default=None, strict=False)
    # Absence is unknown, not an empty observed collection.
    players: Annotated[list[Player], Field(max_length=2000)] | None = None
    teams: Annotated[list[Team], Field(max_length=2000)] | None = None
    candidate_ids: Annotated[list[Identifier], Field(max_length=2000)] | None = None
    contracts: Annotated[list[Contract], Field(max_length=2000)] | None = None
    finances: Annotated[list[ClubFinance], Field(max_length=2000)] | None = None
    fixtures: Annotated[list[Fixture], Field(max_length=2000)] | None = None
    tactics: Annotated[list[Tactic], Field(max_length=128)] | None = None

    @model_validator(mode='after')
    def consistent_collections(self):
        for name, key in [('players','id'), ('teams','id'), ('contracts','player_id'),
                          ('finances','team_id'), ('fixtures','id'), ('tactics','team_id')]:
            rows = getattr(self, name)
            if rows is not None and len({getattr(row, key) for row in rows}) != len(rows):
                raise ValueError('duplicate entity within snapshot')
        if self.candidate_ids is not None and len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError('duplicate candidate id')
        for complete, collection in [('roster_complete','players'), ('candidates_complete','candidate_ids'), ('fixtures_complete','fixtures')]:
            if getattr(self, complete) and getattr(self, collection) is None:
                raise ValueError('complete collection must be observed')
        if self.roster_complete and self.managed_team_id is None:
            raise ValueError('complete roster requires team scope')
        if self.fixture_window_start is not None and self.fixture_window_end is not None and self.fixture_window_end < self.fixture_window_start:
            raise ValueError('fixture window reversed')
        player_ids = {p.id for p in self.players or []}
        if any(p not in player_ids for p in self.candidate_ids or []):
            raise ValueError('candidate identity has no player record')
        if any(c.player_id not in player_ids for c in self.contracts or []):
            raise ValueError('contract identity has no player record')
        return self


def assess_business_snapshot(snapshot: BusinessSnapshot | None, *, now: datetime | None = None,
                             max_age_seconds: float = 15.0) -> dict:
    """Assess structural input coverage; production remains blocked without a producer.

    This deliberately has no caller-supplied verified/ready override. A future
    native producer must establish a reviewed trust boundary before lifting it.
    """
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None or type(max_age_seconds) not in (int, float) or not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= 15:
        raise ValueError('invalid freshness policy')
    reasons = ['native_producer_not_verified']
    requirements = {key: [] for key in ('player_info', 'transfer_analysis', 'tactical_analysis', 'schedule_analysis')}
    source = None
    if snapshot is None:
        reasons.append('no_business_snapshot')
        for missing in requirements.values(): missing.append('business_snapshot')
    else:
        source = snapshot.source.model_dump(mode='json')
        if snapshot.source.synthetic: reasons.append('synthetic_data')
        if snapshot.source.kind != 'native_read': reasons.append('not_native_read')
        if snapshot.source.kind == 'native_read' and snapshot.source.game_plugin_sha256 is None: reasons.append('native_game_plugin_identity_unknown')
        observed = snapshot.source.observed_at
        if observed is None: reasons.append('observation_time_unknown')
        elif not 0 <= (now-observed).total_seconds() <= max_age_seconds: reasons.append('observation_not_fresh')
        if not 0 <= (now-snapshot.source.captured_at).total_seconds() <= max_age_seconds: reasons.append('capture_not_fresh')
        player_missing = requirements['player_info']
        if not snapshot.roster_complete: player_missing.append('complete_scoped_roster')
        if not snapshot.players: player_missing.append('player_records')
        if not any(p.team_id == snapshot.managed_team_id for p in snapshot.players or []): player_missing.append('managed_team_roster')
        if snapshot.managed_team_id is None: player_missing.append('managed_team_identity')
        if not any(t.id == snapshot.managed_team_id and t.name is not None for t in snapshot.teams or []): player_missing.append('managed_team_record')
        for p in snapshot.players or []:
            for field in ('name', 'team_id', 'age', 'positions', 'fitness_percent', 'injured', 'suspended'):
                if getattr(p, field) is None or field == 'positions' and not p.positions:
                    player_missing.append('player.' + field)
            if p.injured is True and p.injury_detail is None: player_missing.append('player.injury_detail')
            if p.suspended is True and p.suspension_detail is None: player_missing.append('player.suspension_detail')
            for category, keys in [('technical', TECHNICAL), ('mental', MENTAL), ('physical', PHYSICAL)]:
                values = getattr(p.attributes, category) if p.attributes else None
                if values is None or values.keys() != keys: player_missing.append('player.attributes.' + category)
        for key in ('transfer_analysis', 'tactical_analysis'):
            requirements[key].extend(player_missing)
        transfer = requirements['transfer_analysis']
        if snapshot.world_date is None: transfer.append('world_date')
        if not snapshot.candidates_complete or snapshot.candidate_scope is None: transfer.append('complete_candidate_scope')
        if snapshot.candidate_ids is None: transfer.append('candidate_ids')
        contracts = {c.player_id: c for c in snapshot.contracts or []}
        for candidate in snapshot.candidate_ids or []:
            c = contracts.get(candidate)
            for field in ('wage', 'expires_on', 'asking_price'):
                if c is None or getattr(c, field) is None: transfer.append('candidate.contract.' + field)
        finance = next((f for f in snapshot.finances or [] if f.team_id == snapshot.managed_team_id), None)
        for field in ('transfer_budget', 'wage_room'):
            if finance is None or getattr(finance, field) is None: transfer.append('club.' + field)
        tactical = requirements['tactical_analysis']
        tactic = next((t for t in snapshot.tactics or [] if t.team_id == snapshot.managed_team_id), None)
        for field in ('formation', 'lineup', 'instructions'):
            if tactic is None or getattr(tactic, field) is None: tactical.append('tactic.' + field)
        if tactic is not None:
            ids = {p.id for p in snapshot.players or [] if p.team_id == tactic.team_id}
            if not tactic.lineup: tactical.append('tactic.lineup_players')
            for slot in tactic.lineup or []:
                if slot.player_id not in ids: tactical.append('tactic.lineup_identity')
                for field in ('role', 'duty', 'instructions'):
                    if getattr(slot, field) is None: tactical.append('tactic.lineup.' + field)
        schedule = requirements['schedule_analysis']
        if snapshot.world_date is None: schedule.append('world_date')
        if snapshot.world_local_time is None: schedule.append('world_local_time')
        if snapshot.world_time_basis is None: schedule.append('world_time_basis')
        if not snapshot.fixtures_complete or snapshot.fixture_window_start is None or snapshot.fixture_window_end is None: schedule.append('complete_fixture_scope')
        if snapshot.managed_team_id is None: schedule.append('fixture_team_scope')
        for fixture in snapshot.fixtures or []:
            if fixture.local_time is None: schedule.append('fixture.local_time')
            if fixture.time_basis is None: schedule.append('fixture.time_basis')
            if snapshot.managed_team_id not in (fixture.home_team_id, fixture.away_team_id): schedule.append('fixture_team_scope')
            if snapshot.fixture_window_start is not None and fixture.date < snapshot.fixture_window_start or snapshot.fixture_window_end is not None and fixture.date > snapshot.fixture_window_end: schedule.append('fixture_window')
        if snapshot.fixtures is None: schedule.append('fixtures')
    return {'schema_version': 'business-readiness/0.1', 'status': 'unavailable',
            'production_ready': False, 'source': source, 'reasons': reasons,
            'capabilities': {key: {'ready': False, 'missing_requirements': sorted(set(missing)),
                **({'scope': 'basic_fixture_congestion', 'missing_rotation_requirements': sorted(set(requirements['player_info']))} if key == 'schedule_analysis' else {})}
                             for key, missing in requirements.items()}}
