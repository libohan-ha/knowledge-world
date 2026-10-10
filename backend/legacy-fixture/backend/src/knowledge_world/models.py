from typing import Annotated, Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

Count = Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]
Version = Annotated[StrictInt, Field(ge=0)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
Content = Annotated[str, Field(max_length=100_000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expected(Input):
    expected_version: Version


class Setup(Input):
    display_name: Name
    password: Annotated[str, Field(min_length=8, max_length=128)]
    timezone: str = "Asia/Shanghai"
    subject_names: list[Name] = Field(
        default_factory=lambda: ["英语", "数学", "政治"], min_length=1, max_length=20
    )


class Login(Input):
    password: str


class ProfileEdit(Expected):
    display_name: Name | None = None
    timezone: str | None = None


class Preferences(Expected):
    reduced_motion: StrictBool | None = None
    notifications: StrictBool | None = None
    world_daylight: StrictBool | None = None


class SubjectCreate(Input):
    name: Name
    theme: Literal["forest", "valley", "plaza"] = "forest"


class SubjectEdit(Expected):
    name: Name | None = None
    theme: Literal["forest", "valley", "plaza"] | None = None
    sort_order: Count | None = None


class ChapterCreate(Input):
    subject_id: str
    title: Name
    sort_order: Count = 0


class ChapterEdit(Expected):
    title: Name | None = None
    sort_order: Count | None = None


class PointCreate(Input):
    subject_id: str
    chapter_id: str | None = None
    source_chunk_id: str | None = None
    title: Name
    content_md: Content = ""
    tags: list[str] = Field(default_factory=list, max_length=30)
    importance: Annotated[StrictInt, Field(ge=1, le=3)] = 2


class PointEdit(Expected):
    title: Name | None = None
    content_md: Content | None = None
    chapter_id: str | None = None
    tags: list[str] | None = None
    importance: Annotated[StrictInt, Field(ge=1, le=3)] | None = None


class CardCreate(Input):
    point_id: str
    type: Literal["single_choice", "multiple_choice", "cloze", "short_answer"]
    question: dict[str, Any]
    answer: dict[str, Any]
    explanation: Content = ""
    source_chunk_id: str | None = None


class CardEdit(Expected):
    question: dict[str, Any] | None = None
    answer: dict[str, Any] | None = None
    explanation: Content | None = None
    state: Literal["draft", "active", "archived"] | None = None


class ChunkEdit(Input):
    id: str
    content_text: Content


class ImportedCard(Input):
    source_chunk_id: str
    point_id: str | None = None
    subject_id: str | None = None
    chapter_id: str | None = None
    point_title: Name
    tags: list[str] = Field(default_factory=list, max_length=30)
    type: Literal["single_choice", "multiple_choice", "cloze", "short_answer"]
    question: dict[str, Any]
    answer: dict[str, Any]
    explanation: Content = ""


class ConfirmMaterial(Expected):
    chunk_edits: list[ChunkEdit] = Field(default_factory=list)
    point_drafts: list[PointCreate] = Field(default_factory=list)
    card_drafts: list[CardCreate] = Field(default_factory=list)
    imported_cards: list[ImportedCard] = Field(default_factory=list, max_length=100)


class GenerateCards(Input):
    confirmed_chunk_ids: list[str]
    allowed_card_types: list[Literal["single_choice", "multiple_choice", "cloze", "short_answer"]]
    count: Annotated[StrictInt, Field(ge=1, le=30)] = 5


class PlanEdit(Expected):
    note: Content = ""


class TaskCreate(Input):
    title: Name
    task_kind: Literal["learning", "personal", "group"] = "learning"
    parent_id: str | None = None
    point_id: str | None = None
    template_code: str | None = None
    acceptance: dict[str, Any] = Field(default_factory=dict)
    difficulty: Literal["light", "standard", "hard", "extreme"] = "standard"
    planned_date: str | None = None
    expected_plan_version: Version | None = None


class PlanTasks(Input):
    items: list[TaskCreate] = Field(min_length=1, max_length=100)
    expected_plan_version: Version


class TaskEdit(Expected):
    title: Name | None = None
    point_id: str | None = None
    template_code: str | None = None
    acceptance: dict[str, Any] | None = None
    difficulty: Literal["light", "standard", "hard", "extreme"] | None = None


class PlanOrder(Input):
    parent_id: str | None = None
    ordered_task_ids: list[str]
    expected_plan_version: Version


class Replan(Expected):
    target_date: str
    expected_source_plan_version: Version
    expected_target_plan_version: Version


class Reopen(Expected):
    reason: Name


class TimerCreate(Input):
    task_id: str | None = None


class ActivityCreate(Input):
    point_id: str
    task_id: str | None = None
    claim_id: str | None = None
    milestone_id: str | None = None
    template_code: str
    narrative_md: Content
    evidence_ids: list[str] = Field(default_factory=list)
    self_reported_occurred_at: str | None = None


class ActivityEdit(Expected):
    narrative_md: Content | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceCreate(Expected):
    kind: Literal["text", "material_chunk", "card_attempt", "attachment"]
    text: Content | None = None
    reference_id: str | None = None


class Reassess(Input):
    reason: Name
    new_evidence_ids: list[str] = Field(default_factory=list)
    expected_claim_version: Version


class PointResult(Input):
    point_id: str
    can_explain: StrictBool
    can_apply_independently: StrictBool
    is_delayed_verification: StrictBool
    supporting_refs: list[str]


class AssessmentPayload(Input):
    verdict: Literal["verified", "progress", "insufficient", "uncertain", "not_met"]
    difficulty: Literal["light", "standard", "hard", "extreme"]
    breakthrough: Literal["none", "clear", "major"]
    additional_progress_steps: Annotated[StrictInt, Field(ge=0, le=2)] = 0
    completed_criteria: list[str]
    missing_criteria: list[str]
    evidence_refs: list[str]
    point_results: list[PointResult]
    reasoning_summary: Annotated[str, Field(min_length=1, max_length=4000)]
    next_action: str


class ReviewRoundCreate(Input):
    subject_id: str | None = None
    include_new: StrictBool = True


class Answer(Expected):
    answer: str | list[str]
    rating: Literal["hard", "good", "easy"] | None = None


class Rating(Expected):
    rating: Literal["hard", "good", "easy"]


class Regrade(Expected):
    reason: Name = "请依据原回答和已确认来源重新判断"


class GradePayload(Input):
    correctness: Literal["correct", "incorrect", "uncertain"]
    matched_criteria: list[str]
    missing_criteria: list[str]
    explanation: str
    source_refs: list[str]


class Viewport(Expected):
    x: Annotated[float, Field(ge=-10000, le=10000)]
    y: Annotated[float, Field(ge=-10000, le=10000)]
    zoom: Annotated[float, Field(ge=0.25, le=3)]


class PlantSeed(Expected):
    seed_item_id: str
    point_id: str


class PlaceItem(Expected):
    plot_id: str
    placement: dict[str, Any] = Field(default_factory=dict)


class EquipItem(Expected):
    companion_id: str


class Interact(Input):
    message: Content = ""


class HabitTerms(Input):
    penalty_enabled: StrictBool = False
    reward_coins: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    penalty_coins: Annotated[StrictInt, Field(ge=0, le=30)] | None = None
    limit_minutes: Annotated[StrictInt, Field(ge=0, le=1440)] | None = None
    scope: Literal["entertainment", "all_screen"] | None = None
    condition: Content = "完成当天约定"


class HabitCreate(Input):
    kind: Literal["checkin", "screen_time", "custom"]
    title: Name
    weekdays: list[Annotated[StrictInt, Field(ge=0, le=6)]] = Field(default_factory=lambda: list(range(7)))
    terms: HabitTerms = Field(default_factory=HabitTerms)


class HabitRevision(Expected):
    weekdays: list[Annotated[StrictInt, Field(ge=0, le=6)]] | None = None
    terms: HabitTerms | None = None


class HabitComplete(Expected):
    note: Content = ""


class CheckinComplete(Expected):
    startup_attempt_id: str


class ScreenRecord(Input):
    minutes: Annotated[StrictInt, Field(ge=0, le=1440)]
    scope: Literal["entertainment", "all_screen"] = "entertainment"
    note: Content = ""
    expected_revision: Version


class CommitmentProposal(Input):
    title: Name
    target_points: Annotated[StrictInt, Field(gt=0, le=10000)]
    stake_coins: Annotated[StrictInt, Field(gt=0, le=500)]
    bonus_coins: Annotated[StrictInt, Field(ge=0, le=800)]
    deadline_at: str | None = None


class AcceptTerms(Expected):
    terms_hash: str


class Quote(Input):
    catalog_code: str
    input: dict[str, Any] = Field(default_factory=dict)


class Redeem(Input):
    quote_token: str


class Favorite(Expected):
    favorite: StrictBool


class StoryCreate(Input):
    title: Name
    bible: dict[str, Any]


class StoryEdit(Expected):
    title: Name | None = None
    bible: dict[str, Any] | None = None


class ChapterPayload(Input):
    chapter_number: Annotated[StrictInt, Field(ge=1)]
    title: Name
    body_markdown: str
    chapter_summary: str
    continuity_updates: list[str]


class ProviderConfig(Input):
    base_url: str
    model: Name
    api_key: str | None = None
    secret_env: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    expected_version: Version = 0


class RuleChange(Input):
    based_on_version: str
    changes: dict[str, Any]


class ThreadCreate(Input):
    title: Name = "新的复盘"
    context: dict[str, Any] = Field(default_factory=dict)


class MessageCreate(Input):
    content: Annotated[str, Field(min_length=1, max_length=20000)]
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    context_refs: dict[str, Any] = Field(default_factory=dict)
    client_message_id: str


class ActionConfirm(Input):
    action_hash: str


class ReportCreate(Input):
    period_kind: Literal["day", "week"]
    start_date: str
    end_date: str


class RetryJob(Input):
    expected_state: str


class Restore(Input):
    preview_token: str


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class Wallet(BaseModel):
    learning_points: int
    available_coins: int
    held_coins: int
    version: int


class View(BaseModel):
    model_config = ConfigDict(extra="allow")


class CurrentUser(View):
    profile: dict[str, Any]
    wallet: Wallet
    business_date: str
    is_test_adapter: bool
    display_epoch: str


class TaskView(View):
    id: str
    title: str
    task_kind: Literal["learning", "personal", "group"]
    point_id: str | None
    parent_id: str | None
    planned_date: str | None
    plan_order: int
    execution_state: str
    unlock_state: Literal["locked", "unlocked"]
    template_code: str | None
    completed_at: str | None
    version: int
    acceptance: dict[str, Any]
    quoted_terms: dict[str, Any]


class DailyPlan(View):
    id: str | None
    date: str
    note: str
    tasks: list[TaskView]
    total_top_level: int
    unlocked_top_level: int
    version: int


class PointView(View):
    id: str
    title: str
    subject_id: str
    chapter_id: str | None
    content_md: str
    tags: list[str]
    current_stage: str
    best_stage: str
    review_state: str
    next_review_at: str | None
    version: int


class AttemptView(View):
    id: str
    question: dict[str, Any]
    card_type: str
    grading_state: str
    correctness: str | None
    independent: bool
    rating: str | None
    version: int


class Receipt(View):
    id: str
    learning_delta: int
    available_delta: int
    held_delta: int
    business_date: str
    entry_type: str
    source_key: str
    rule_version: str
    created_at: str
    detail: dict[str, Any]


WorldStage = Literal['unseen', 'exploring', 'understood', 'applicable', 'consolidated']


class WorldPresentationState(BaseModel):
    current_stage: WorldStage | None = None
    best_stage: WorldStage | None = None
    landmark_present: StrictBool | None = None


class WorldHistorySource(BaseModel):
    kind: Literal['assessment', 'achievement']
    id: str
    activity_id: str | None = None


class WorldHistoryEvent(BaseModel):
    id: str
    event_key: str
    kind: Literal['learning', 'chapter_landmark']
    occurred_at: str
    region_id: str | None
    plot_id: str | None
    point_id: str | None
    chapter_id: str | None
    source: WorldHistorySource | None
    ledger_id: str | None
    learning_business_date: str | None
    presentation_version: int | None
    before: WorldPresentationState
    after: WorldPresentationState
    is_correction: StrictBool | None
    coverage: Literal['complete', 'partial']
    missing_fields: list[str]


class WorldHistoryRange(BaseModel):
    date_from: str
    date_to: str
    timezone: str


class WorldHistoryCoverage(BaseModel):
    event_total: int
    complete_state_total: int
    partial_state_total: int


class WorldHistoryPage(BaseModel):
    items: list[WorldHistoryEvent]
    next_cursor: str | None
    as_of: str
    snapshot_token: str
    range: WorldHistoryRange
    coverage: WorldHistoryCoverage
