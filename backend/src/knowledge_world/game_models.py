"""Pydantic is the source of the generated frontend game contract."""
from typing import Any, Literal
from pydantic import BaseModel, Field, StrictInt, StrictBool
from .models import Input, Expected, Name, Count, ProfileView


class PointsWallet(BaseModel):
    available_points: int
    held_points: int
    version: int


class FixedTaskEdit(Input):
    title: Name
    description: str = Field(default='', max_length=4000)
    reward_points: StrictInt = Field(ge=0, le=200)
    expected_version: Count | None = None


class FixedTask(BaseModel):
    id: str
    title: str
    description: str
    reward_points: int
    version: int


class FixedTaskComplete(Input):
    completion_id: str = Field(min_length=8, max_length=128)


class FixedTaskReceipt(BaseModel):
    completion_id: str
    task_id: str
    title: str
    awarded_points: int
    ledger_entry_ids: list[str]
    game_event_ids: list[str]
    wallet: PointsWallet


class Stats(BaseModel):
    hp: int
    physical_attack: int
    magic_attack: int
    defense: int
    resistance: int
    speed: int
    mp: int
    dodge_bps: int = 0


class Skill(BaseModel):
    code: str
    effect: str
    amount: int | None = None
    power_bps: int = 10000
    mp_cost: int
    every_nth_action: int


class Attributes(BaseModel):
    strength: int
    agility: int
    mana: int


class Unit(BaseModel):
    id: str
    code: str
    name: str
    role: str
    level: int
    visual_stage: int
    stats: Stats
    skill: Skill | None
    version: int
    attributes: Attributes | None = None
    training_steps: int | None = None
    next_cost: int | None = None
    next_stage_level: int | None = None
    side: str | None = None
    position: int | None = None


class Species(BaseModel):
    code: str
    name: str
    role: str
    recruit_cost: int
    stats: Stats
    skill: Skill


class Team(BaseModel):
    member_ids: list[str]
    version: int


class Roster(BaseModel):
    hero: Unit
    monsters: list[Unit]
    species: list[Species]
    team: Team
    max_deployed: int
    rule_version: str


class TeamChange(Expected):
    member_ids: list[str] = Field(min_length=1, max_length=4)


class GameQuote(Input):
    operation: Literal["hero_train", "monster_recruit", "monster_train", "home_buy", "home_upgrade", "leisure"]
    target_id: str | None = None
    attribute: Literal["strength", "agility", "mana"] | None = None


class QuoteResult(BaseModel):
    quote_token: str
    quote_id: str
    operation: str
    name: str
    price_points: int
    before: dict[str, Any]
    after: dict[str, Any]
    rule_version: str
    expires_at: str


class Purchase(Input):
    quote_token: str


class CommandReceipt(BaseModel):
    command_id: str
    operation: str
    entity_id: str
    entity_version: int
    price_points: int = 0
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ledger_entry_ids: list[str]
    game_event_ids: list[str]
    wallet: PointsWallet
    rule_version: str


class HomeItem(BaseModel):
    id: str
    code: str
    name: str
    kind: str
    level: int
    x: int | None
    z: int | None
    rotation: int
    footprint: int
    version: int
    legacy_ref: dict[str, Any] | None = None
    rule_version: str
    grant_key: str


class HomeDecoration(BaseModel):
    code: str
    name: str
    price_points: int


class Home(BaseModel):
    items: list[HomeItem]
    catalog: list[HomeDecoration]
    roster: Roster
    occupations: list[str]
    display_epoch: str
    grid_min: int
    grid_max: int
    rule_version: str


class Placement(Expected):
    x: StrictInt | None = None
    z: StrictInt | None = None
    rotation: Literal[0, 90, 180, 270] = 0


class Enemy(BaseModel):
    code: str
    name: str
    stats: Stats
    skill: Skill | None
    visual_stage: int


class Position(BaseModel):
    x: int
    z: int


class Outpost(BaseModel):
    id: str
    name: str
    description: str
    region_id: str
    theme: str
    is_boss: bool
    prerequisites: list[str]
    enemies: list[Enemy]
    position: Position
    reward_points: int
    trophy_code: str | None
    status: Literal["locked", "available", "occupied"]


class Region(BaseModel):
    id: str
    name: str
    description: str
    theme: str


class WorldMap(BaseModel):
    version: str
    regions: list[Region]
    outposts: list[Outpost]
    team: Team


class BattleCreate(Input):
    outpost_id: str
    team_version: Count
    command_key: str = Field(min_length=8, max_length=128)


class CombatState(BaseModel):
    hp: int
    mp: int
    shield: int


class BattleEvent(BaseModel):
    sequence: int
    round: int
    actor_id: str
    target_id: str
    action: str
    effect: str
    damage_type: str | None
    damage: int
    absorbed: int
    healing: int
    shield_gain: int
    dodged: bool
    died: bool
    actor_before: CombatState
    actor_after: CombatState
    target_before: CombatState
    target_after: CombatState


class BattleSnapshot(BaseModel):
    allies: list[Unit]
    enemies: list[Unit]
    outpost: Outpost
    battle_rules: dict[str, Any]
    team_version: int


class BattleResult(BaseModel):
    outcome: Literal["won", "lost"]
    reason: str
    rounds: int
    events: list[BattleEvent]
    final_states: dict[str, CombatState]
    first_clear: bool
    reward_points: int
    reward_item_id: str | None
    occupation_changed: bool
    ledger_entry_ids: list[str]
    game_event_ids: list[str]
    command_id: str
    wallet: PointsWallet


class Battle(BaseModel):
    id: str
    outpost_id: str
    state: str
    rule_version: str
    catalog_version: str
    seed: str
    engine_version: str
    snapshot: BattleSnapshot
    result: BattleResult | None
    job_id: str
    created_at: str
    completed_at: str | None


class RewardEdit(Input):
    name: Name
    description: str = Field(default="", max_length=4000)
    price_points: StrictInt = Field(ge=0, le=10000)
    duration_minutes: StrictInt = Field(ge=1, le=1440)
    expected_version: Count | None = None


class Reward(BaseModel):
    id: str
    code: str
    name: str
    description: str
    price_points: int
    duration_minutes: int
    version: int


class LeisureTicket(BaseModel):
    id: str
    catalog_id: str
    snapshot: Reward
    price_points: int
    duration_seconds: int
    used_seconds: int
    remaining_seconds: int
    state: str
    first_started_at: str | None
    running_since: str | None
    version: int
    rule_version: str
    server_time: str
    ledger_entry_ids: list[str]
    game_event_ids: list[str]


class ActionCreate(Input):
    client_action_id: str = Field(min_length=8, max_length=128)
    content: str = Field(min_length=1, max_length=20000)


class ActionRevision(Expected):
    content: str = Field(min_length=1, max_length=20000)


class SystemJudgment(Input):
    points: StrictInt = Field(ge=-10000, le=10000)
    reason: str = Field(min_length=1, max_length=4000)
    basis: str = Field(default="action", max_length=200)
    status: Literal["decided", "needs_review", "no_action"] = "decided"


class Decision(BaseModel):
    id: str
    action_id: str
    action_version: int
    proposed_points: int
    approved_points: int
    applied_delta: int
    reason: str
    basis: str
    state: str
    review_code: str | None
    supersedes_id: str | None
    ledger_id: str | None
    rule_version: str
    model_info: dict[str, Any]
    created_at: str
    applied_at: str | None


class Action(BaseModel):
    id: str
    source_kind: str
    source: dict[str, Any]
    state: str
    net_points: int
    version: int
    content: str
    decisions: list[Decision]
    job_id: str | None
    first_submitted_at: str


class Adjustment(Input):
    points: StrictInt = Field(ge=-10000, le=10000)
    reason: str = Field(min_length=3, max_length=1000)
    command_key: str = Field(min_length=8, max_length=128)


class ChallengeProposal(Input):
    title: Name
    goal: str = Field(min_length=1, max_length=4000)
    reward_points: StrictInt = Field(ge=0, le=200)
    penalty_points: StrictInt = Field(default=0, ge=0, le=100)
    penalty_condition: str = Field(default="", max_length=2000)
    deadline_at: str | None = None


class ChallengeResolve(Expected):
    outcome: Literal["completed", "failed", "cancelled", "needs_review"]
    evidence: str = Field(min_length=1, max_length=10000)
    action_id: str | None = None


class Challenge(BaseModel):
    id: str
    title: str
    goal: str
    reward_points: int
    penalty_points: int
    penalty_condition: str
    state: str
    version: int
    terms: dict[str, Any]
    terms_hash: str
    rule_version: str
    action_id: str | None
    deadline_at: str | None


class WagerProposal(Input):
    title: Name = "向自己发起挑战"
    target_points: StrictInt = Field(default=500, ge=1, le=100000)
    stake_points: StrictInt = Field(default=500, ge=1, le=500)
    bonus_points: StrictInt = Field(default=800, ge=0, le=800)
    deadline_at: str | None = None


class Wager(BaseModel):
    id: str
    title: str
    target_points: int
    stake_points: int
    bonus_points: int
    progress_points: int
    pending_assessments: int
    state: str
    terms: dict[str, Any]
    terms_hash: str
    version: int
    rule_version: str
    accepted_at: str | None
    deadline_at: str
    grace_deadline_at: str
    timezone_snapshot: str
    settlement_ledger_id: str | None
    legacy_compatibility: bool
    ledger_entry_ids: list[str]
    game_event_ids: list[str]


class Checkin(BaseModel):
    occurrence: dict[str, Any]
    eligible: bool
    window: str
    terms: dict[str, Any]
    message: str
    streak: int
    awarded_points: int
    ledger_entry_ids: list[str]
    game_event_ids: list[str]
    server_time: str


class CheckinSettings(Input):
    expected_version: Count
    penalty_enabled: StrictBool
    weekdays: list[StrictInt] = Field(default_factory=lambda: list(range(7)), min_length=0, max_length=7)


class PenaltyRuleCreate(Input):
    title: Name
    condition: str = Field(min_length=1, max_length=2000)
    points: StrictInt = Field(ge=0, le=100)


class SkillSetting(Input):
    skill: Literal["wager", "shiyi"]
    enabled: StrictBool
    expected_version: Count


class LegacyFact(Input):
    client_fact_id: str = Field(min_length=8, max_length=128)
    title: Name
    evidence: str = Field(min_length=30, max_length=20000)
    point_id: str | None = None
    template_code: str = "new_knowledge"


class HistoryEvent(BaseModel):
    id: str
    sequence: int
    kind: str
    object_id: str | None
    region_id: str | None
    origin_type: str
    origin_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    receipt: dict[str, Any]
    rule_version: str
    business_date: str
    created_at: str


class HistoryPage(BaseModel):
    items: list[HistoryEvent]
    next_cursor: str | None
    upper_sequence: int
    display_epoch: str
    coverage: dict[str, Any]


class LedgerEntry(BaseModel):
    id: str
    sequence: int
    entry_type: str
    economic_kind: str
    available_delta: int
    held_delta: int
    business_date: str
    created_at: str
    origin_type: str
    origin_id: str
    source_key: str
    rule_version: str
    correction_of: str | None
    detail: dict[str, Any]


class SystemContext(BaseModel):
    wallet: PointsWallet
    roster: Roster
    actions: list[Action]
    challenges: list[Challenge]
    wagers: list[Wager]
    recent_events: list[HistoryEvent]
    rules: dict[str, Any]
    is_test_adapter: bool
    ai_available: bool


class EventFeed(BaseModel):
    items: list[HistoryEvent]
    last_sequence: int
    has_more: bool
    display_epoch: str


class LedgerSource(BaseModel):
    ledger: LedgerEntry
    source: dict[str, Any] | None
    read_only: bool


class AdjustmentReceipt(BaseModel):
    wallet: PointsWallet
    ledger_entry_ids: list[str]
    game_event_ids: list[str]


class BackgroundJob(BaseModel):
    id: str
    kind: str
    state: str
    can_retry: bool
    can_cancel: bool
    last_error: dict[str, Any] | None
    result: dict[str, Any] | None
    created_at: str
    updated_at: str
    is_test_adapter: bool


class AgentMessage(BaseModel):
    id: str
    role: str
    content_md: str
    run_id: str | None
    created_at: str


class AgentRun(BaseModel):
    id: str
    job_id: str | None
    state: str
    created_at: str


class ToolCard(BaseModel):
    id: str
    tool_name: str
    result: dict[str, Any]
    state: str
    action_hash: str


class AgentThread(BaseModel):
    id: str
    title: str
    created_at: str
    messages: list[AgentMessage] = Field(default_factory=list)
    runs: list[AgentRun] = Field(default_factory=list)
    actions: list[ToolCard] = Field(default_factory=list)


class MessageReceipt(BaseModel):
    thread_id: str
    message_id: str
    run_id: str
    job_id: str
    state: str
    message: str | None = None


class Notification(BaseModel):
    id: str
    title: str
    body: str
    target_path: str
    created_at: str


class SkillView(BaseModel):
    skill: str
    enabled: bool
    version: int
    available: bool
    status: Literal["ready", "disabled", "not_configured", "missing_credentials", "needs_check", "connection_error"]
    settings_path: str


class SkillDirectory(BaseModel):
    skills: list[SkillView]
    tools: list[dict[str, Any]]


class ProviderView(BaseModel):
    id: str
    role: str
    base_url: str
    model: str
    enabled: bool
    has_secret: bool
    capabilities: dict[str, Any]
    version: int


class AppSettings(BaseModel):
    profile: ProfileView
    providers: list[ProviderView]
    is_test_adapter: bool
    mode: str
    sqlite_version: str
    rules_version: str
    jobs: list[BackgroundJob]


class RulesView(BaseModel):
    rules: dict[str, Any]
    locked_paths: list[str]


class PenaltyRule(BaseModel):
    id: str
    title: str
    condition: str
    points: int
    effective_date: str
    disabled_at: str | None
    rule_version: str


class LegacyOrder(BaseModel):
    id: str
    name: str
    state: str
    version: int
    price_points: int
    rule_version: str
    created_at: str
    asset_id: str | None
    ledger_entry_ids: list[str]
    can_close: bool


class LegacyOrderClose(Expected):
    reason: str = Field(min_length=3, max_length=1000)


class LegacyFactView(BaseModel):
    id: str
    version: int
    state: str
    narrative_md: str
    claim: dict[str, Any]
    assessments: list[dict[str, Any]]
    receipts: list[LedgerEntry]
    evidence: list[dict[str, Any]]
    job_id: str | None
