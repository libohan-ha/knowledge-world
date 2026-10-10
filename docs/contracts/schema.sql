-- 知识世界初始数据库契约。应用尚未实现。
-- 时间：UTC Unix 毫秒；业务日：YYYY-MM-DD；ID：应用生成的 UUID。
-- 发布运行时要求见技术架构；本 DDL 可用临时数据库进行结构校验。
-- 全部连接启用 foreign_keys；WAL 在运行时初始化，不在本结构脚本强制启用。
PRAGMA foreign_keys = ON;

CREATE TABLE profiles (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    pending_timezone TEXT,
    timezone_effective_date TEXT,
    preferences_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(preferences_json)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE auth_sessions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked_at INTEGER,
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE rule_versions (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
    created_at INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX one_active_rule ON rule_versions(is_active) WHERE is_active = 1;
CREATE TRIGGER rule_payload_immutable BEFORE UPDATE ON rule_versions
WHEN NEW.id IS NOT OLD.id OR NEW.payload_json IS NOT OLD.payload_json
BEGIN SELECT RAISE(ABORT,'rule_payload_is_immutable'); END;

CREATE TABLE provider_configs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    role TEXT NOT NULL CHECK(role IN ('chat','vision','image')),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    capabilities_json TEXT NOT NULL CHECK(json_valid(capabilities_json)),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(owner_id,role)
) STRICT;

CREATE TABLE subjects (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    name TEXT NOT NULL,
    theme TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    archived_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE chapters (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    subject_id TEXT NOT NULL REFERENCES subjects(id),
    title TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    archived_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE materials (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    subject_id TEXT REFERENCES subjects(id),
    title TEXT NOT NULL,
    media_type TEXT NOT NULL,
    relative_path TEXT,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0 CHECK(size_bytes >= 0),
    state TEXT NOT NULL CHECK(state IN ('uploaded','parsing','needs_confirmation','ready','failed','archived')),
    parser_info_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(parser_info_json)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(owner_id,sha256)
) STRICT;

CREATE TABLE material_chunks (
    id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    locator_json TEXT NOT NULL CHECK(json_valid(locator_json)),
    content_text TEXT NOT NULL,
    confirmed_at INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(material_id,ordinal)
) STRICT;

CREATE TABLE knowledge_points (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    subject_id TEXT NOT NULL REFERENCES subjects(id),
    chapter_id TEXT REFERENCES chapters(id),
    source_chunk_id TEXT REFERENCES material_chunks(id),
    title TEXT NOT NULL,
    content_md TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags_json)),
    importance INTEGER NOT NULL DEFAULT 2 CHECK(importance BETWEEN 1 AND 3),
    archived_at INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE cards (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    point_id TEXT NOT NULL REFERENCES knowledge_points(id),
    source_chunk_id TEXT REFERENCES material_chunks(id),
    card_type TEXT NOT NULL CHECK(card_type IN ('single_choice','multiple_choice','cloze','short_answer')),
    question_json TEXT NOT NULL CHECK(json_valid(question_json)),
    answer_json TEXT NOT NULL CHECK(json_valid(answer_json)),
    explanation_md TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK(state IN ('draft','active','archived')),
    is_verification INTEGER NOT NULL DEFAULT 0 CHECK(is_verification IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE daily_plans (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    business_date TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(owner_id,business_date)
) STRICT;

CREATE TABLE study_tasks (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    parent_id TEXT REFERENCES study_tasks(id),
    point_id TEXT REFERENCES knowledge_points(id),
    plan_id TEXT REFERENCES daily_plans(id),
    plan_order INTEGER NOT NULL DEFAULT 0 CHECK(plan_order >= 0),
    title TEXT NOT NULL,
    task_kind TEXT NOT NULL DEFAULT 'learning' CHECK(task_kind IN ('learning','personal','group')),
    template_code TEXT,
    acceptance_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(acceptance_json)),
    quoted_terms_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(quoted_terms_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    state TEXT NOT NULL CHECK(state IN ('draft','ready','in_progress','submitted','completed','archived')),
    completed_at INTEGER,
    completion_business_date TEXT,
    completion_activity_id TEXT REFERENCES activities(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    CHECK(task_kind != 'learning' OR
          (state IN ('draft','archived') AND completed_at IS NULL) OR
          (template_code IS NOT NULL AND point_id IS NOT NULL)),
    CHECK((completed_at IS NULL AND completion_business_date IS NULL AND completion_activity_id IS NULL) OR
          (completed_at IS NOT NULL AND completion_business_date IS NOT NULL AND
           (task_kind != 'learning' OR completion_activity_id IS NOT NULL))),
    CHECK(state IN ('completed','archived') OR completed_at IS NULL),
    CHECK(state != 'completed' OR completed_at IS NOT NULL),
    CHECK(task_kind = 'learning' OR completion_activity_id IS NULL)
) STRICT;
CREATE INDEX task_plan_order ON study_tasks(plan_id,plan_order,id);
CREATE INDEX task_owner_completion ON study_tasks(owner_id,completion_business_date);

CREATE TABLE timer_sessions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    task_id TEXT REFERENCES study_tasks(id),
    state TEXT NOT NULL CHECK(state IN ('running','paused','stopped')),
    accumulated_seconds INTEGER NOT NULL DEFAULT 0 CHECK(accumulated_seconds >= 0),
    segment_started_at INTEGER,
    segments_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(segments_json)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX one_running_timer ON timer_sessions(owner_id) WHERE state = 'running';

CREATE TABLE learning_claims (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    canonical_key TEXT NOT NULL,
    task_id TEXT REFERENCES study_tasks(id),
    point_id TEXT NOT NULL REFERENCES knowledge_points(id),
    template_code TEXT NOT NULL,
    quoted_terms_json TEXT NOT NULL CHECK(json_valid(quoted_terms_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    first_submitted_at INTEGER,
    first_business_date TEXT,
    timezone_snapshot TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    UNIQUE(owner_id,canonical_key)
) STRICT;

CREATE TABLE activities (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    claim_id TEXT NOT NULL REFERENCES learning_claims(id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('task','chat','review','manual')),
    submission_group_id TEXT,
    narrative_md TEXT NOT NULL,
    self_reported_occurred_at INTEGER,
    submitted_at INTEGER,
    business_date TEXT,
    state TEXT NOT NULL CHECK(state IN ('draft','submitted','assessing','needs_evidence','needs_review','settled','failed')),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE evidence_items (
    id TEXT PRIMARY KEY,
    activity_id TEXT NOT NULL REFERENCES activities(id),
    kind TEXT NOT NULL CHECK(kind IN ('text','material_chunk','card_attempt','attachment')),
    material_chunk_id TEXT REFERENCES material_chunks(id),
    card_attempt_id TEXT REFERENCES card_attempts(id),
    material_id TEXT REFERENCES materials(id),
    content_text TEXT,
    sha256 TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(activity_id,sha256)
) STRICT;

CREATE TABLE assessments (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    claim_id TEXT NOT NULL REFERENCES learning_claims(id),
    activity_id TEXT NOT NULL REFERENCES activities(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    supersedes_id TEXT REFERENCES assessments(id),
    verdict TEXT NOT NULL CHECK(verdict IN ('verified','progress','insufficient','uncertain','not_met')),
    state TEXT NOT NULL CHECK(state IN ('proposed','accepted','superseded','rejected')),
    difficulty TEXT NOT NULL CHECK(difficulty IN ('light','standard','hard','extreme')),
    breakthrough TEXT NOT NULL CHECK(breakthrough IN ('none','clear','major')),
    additional_progress_steps INTEGER NOT NULL DEFAULT 0 CHECK(additional_progress_steps >= 0),
    reasoning_summary TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL CHECK(json_valid(evidence_refs_json)),
    point_results_json TEXT NOT NULL CHECK(json_valid(point_results_json)),
    rubric_json TEXT NOT NULL CHECK(json_valid(rubric_json)),
    model_info_json TEXT NOT NULL CHECK(json_valid(model_info_json)),
    target_points INTEGER NOT NULL DEFAULT 0 CHECK(target_points >= 0),
    reward_category TEXT NOT NULL CHECK(reward_category IN ('deep_learning','micro_review','productive_attempt')),
    evidence_cutoff_at INTEGER NOT NULL,
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    created_at INTEGER NOT NULL,
    accepted_at INTEGER,
    UNIQUE(claim_id,revision)
) STRICT;

CREATE TABLE card_attempts (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    card_id TEXT NOT NULL REFERENCES cards(id),
    activity_id TEXT REFERENCES activities(id),
    occurrence_kind TEXT NOT NULL CHECK(occurrence_kind IN ('review','verification','startup')),
    opportunity_key TEXT NOT NULL,
    schedule_generation INTEGER,
    question_version INTEGER NOT NULL,
    frozen_question_json TEXT NOT NULL CHECK(json_valid(frozen_question_json)),
    frozen_answer_json TEXT NOT NULL CHECK(json_valid(frozen_answer_json)),
    answer_json TEXT CHECK(answer_json IS NULL OR json_valid(answer_json)),
    revealed_at INTEGER,
    answered_at INTEGER,
    independent INTEGER NOT NULL DEFAULT 0 CHECK(independent IN (0,1)),
    grading_state TEXT NOT NULL CHECK(grading_state IN ('unanswered','pending','graded','needs_review')),
    correctness TEXT CHECK(correctness IN ('correct','incorrect','uncertain')),
    rating TEXT CHECK(rating IN ('again','hard','good','easy')),
    explanation_md TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE verification_items (
    id TEXT PRIMARY KEY,
    activity_id TEXT NOT NULL REFERENCES activities(id),
    card_attempt_id TEXT NOT NULL UNIQUE REFERENCES card_attempts(id),
    criterion_key TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0,1)),
    created_at INTEGER NOT NULL,
    UNIQUE(activity_id,criterion_key)
) STRICT;

CREATE TABLE learning_awards (
    claim_id TEXT PRIMARY KEY REFERENCES learning_claims(id),
    current_assessment_id TEXT NOT NULL REFERENCES assessments(id),
    current_points INTEGER NOT NULL DEFAULT 0 CHECK(current_points >= 0),
    coin_high_water INTEGER NOT NULL DEFAULT 0 CHECK(coin_high_water >= 0),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE wallets (
    owner_id TEXT PRIMARY KEY REFERENCES profiles(id),
    learning_points INTEGER NOT NULL DEFAULT 0 CHECK(learning_points >= 0),
    available_coins INTEGER NOT NULL DEFAULT 0 CHECK(available_coins >= 0),
    held_coins INTEGER NOT NULL DEFAULT 0 CHECK(held_coins >= 0),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE ledger_entries (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL REFERENCES wallets(owner_id),
    entry_type TEXT NOT NULL CHECK(entry_type IN (
      'learning_grant','learning_correction','habit_reward','habit_penalty',
      'commitment_hold','commitment_win','commitment_loss','commitment_refund',
      'redemption_hold','redemption_spend','redemption_refund','purchase','achievement'
    )),
    category TEXT NOT NULL CHECK(category IN ('deep_learning','micro_review','productive_attempt','habit','commitment','shop','achievement')),
    source_key TEXT NOT NULL,
    origin_type TEXT NOT NULL,
    origin_id TEXT NOT NULL,
    claim_id TEXT REFERENCES learning_claims(id),
    assessment_id TEXT REFERENCES assessments(id),
    learning_delta INTEGER NOT NULL DEFAULT 0,
    available_delta INTEGER NOT NULL DEFAULT 0,
    held_delta INTEGER NOT NULL DEFAULT 0,
    business_date TEXT NOT NULL,
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    detail_json TEXT NOT NULL CHECK(json_valid(detail_json)),
    created_at INTEGER NOT NULL,
    CHECK(learning_delta != 0 OR available_delta != 0 OR held_delta != 0),
    UNIQUE(owner_id,source_key)
) STRICT;
CREATE INDEX ledger_owner_day ON ledger_entries(owner_id,business_date,category);
CREATE INDEX ledger_claim ON ledger_entries(claim_id,sequence);
CREATE TRIGGER ledger_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE(ABORT,'ledger_is_append_only'); END;
CREATE TRIGGER ledger_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE(ABORT,'ledger_is_append_only'); END;
CREATE TRIGGER ledger_apply_balance AFTER INSERT ON ledger_entries
BEGIN
    UPDATE wallets
    SET learning_points = learning_points + NEW.learning_delta,
        available_coins = available_coins + NEW.available_delta,
        held_coins = held_coins + NEW.held_delta,
        version = version + 1,
        updated_at = NEW.created_at
    WHERE owner_id = NEW.owner_id;
END;

CREATE TABLE review_schedules (
    card_id TEXT PRIMARY KEY REFERENCES cards(id),
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    stage_index INTEGER NOT NULL DEFAULT 0 CHECK(stage_index >= 0),
    due_at INTEGER NOT NULL,
    opportunity_key TEXT NOT NULL UNIQUE,
    generation INTEGER NOT NULL DEFAULT 1,
    relearning INTEGER NOT NULL DEFAULT 0 CHECK(relearning IN (0,1)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
) STRICT;
CREATE INDEX review_owner_due ON review_schedules(owner_id,due_at);

CREATE TABLE review_rounds (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    filters_json TEXT NOT NULL CHECK(json_valid(filters_json)),
    state TEXT NOT NULL CHECK(state IN ('active','completed','ended')),
    current_ordinal INTEGER NOT NULL DEFAULT 0 CHECK(current_ordinal >= 0),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    completed_at INTEGER
) STRICT;

CREATE TABLE review_round_items (
    round_id TEXT NOT NULL REFERENCES review_rounds(id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    attempt_id TEXT NOT NULL UNIQUE REFERENCES card_attempts(id),
    PRIMARY KEY(round_id,ordinal)
) STRICT;

CREATE TABLE review_events (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    card_id TEXT NOT NULL REFERENCES cards(id),
    attempt_id TEXT NOT NULL UNIQUE REFERENCES card_attempts(id),
    schedule_generation INTEGER NOT NULL,
    before_json TEXT NOT NULL CHECK(json_valid(before_json)),
    after_json TEXT NOT NULL CHECK(json_valid(after_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    created_at INTEGER NOT NULL,
    UNIQUE(card_id,schedule_generation)
) STRICT;

CREATE TABLE point_mastery (
    point_id TEXT PRIMARY KEY REFERENCES knowledge_points(id),
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    current_stage INTEGER NOT NULL DEFAULT 0 CHECK(current_stage BETWEEN 0 AND 4),
    best_stage INTEGER NOT NULL DEFAULT 0 CHECK(best_stage BETWEEN 0 AND 4),
    first_application_at INTEGER,
    latest_verification_at INTEGER,
    delayed_pass_count INTEGER NOT NULL DEFAULT 0 CHECK(delayed_pass_count >= 0),
    consolidated_at INTEGER,
    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_snapshot_json)),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL,
    CHECK(best_stage >= current_stage)
) STRICT;

CREATE TABLE world_regions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    subject_id TEXT NOT NULL UNIQUE REFERENCES subjects(id),
    theme TEXT NOT NULL,
    layout_seed TEXT NOT NULL,
    layout_version INTEGER NOT NULL DEFAULT 1,
    viewport_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(viewport_json)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE world_plots (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL REFERENCES world_regions(id),
    point_id TEXT UNIQUE REFERENCES knowledge_points(id),
    grid_x INTEGER NOT NULL,
    grid_y INTEGER NOT NULL,
    terrain TEXT NOT NULL,
    unlocked_at INTEGER,
    decoration_layout_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(decoration_layout_json)),
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(region_id,grid_x,grid_y)
) STRICT;

CREATE TABLE world_events (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    event_key TEXT NOT NULL,
    point_id TEXT REFERENCES knowledge_points(id),
    ledger_id TEXT REFERENCES ledger_entries(id),
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    created_at INTEGER NOT NULL,
    UNIQUE(owner_id,event_key)
) STRICT;

CREATE TABLE catalog_items (
    code TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('seed','decoration','upgrade','outfit','image','chapter','collectible')),
    name TEXT NOT NULL,
    price_coins INTEGER NOT NULL CHECK(price_coins >= 0),
    requirements_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(requirements_json)),
    asset_key TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    purchasable INTEGER NOT NULL DEFAULT 1 CHECK(purchasable IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE TABLE inventory_items (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    catalog_code TEXT NOT NULL REFERENCES catalog_items(code),
    grant_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('owned','placed','consumed','equipped')),
    placed_plot_id TEXT REFERENCES world_plots(id),
    placement_json TEXT CHECK(placement_json IS NULL OR json_valid(placement_json)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    UNIQUE(owner_id,grant_key)
) STRICT;

CREATE TABLE plants (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    plot_id TEXT NOT NULL REFERENCES world_plots(id),
    point_id TEXT NOT NULL REFERENCES knowledge_points(id),
    seed_item_id TEXT NOT NULL UNIQUE REFERENCES inventory_items(id),
    growth_stage INTEGER NOT NULL DEFAULT 0 CHECK(growth_stage BETWEEN 0 AND 2),
    state TEXT NOT NULL CHECK(state IN ('growing','mature','harvested')),
    harvest_item_id TEXT UNIQUE REFERENCES inventory_items(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    harvested_at INTEGER
) STRICT;
CREATE UNIQUE INDEX one_live_plant_per_plot ON plants(plot_id) WHERE state != 'harvested';

CREATE TABLE companions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL UNIQUE REFERENCES profiles(id),
    name TEXT NOT NULL,
    affinity INTEGER NOT NULL DEFAULT 0 CHECK(affinity >= 0),
    outfit_item_id TEXT UNIQUE REFERENCES inventory_items(id),
    profile_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(profile_json)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE companion_interactions (
    id TEXT PRIMARY KEY,
    companion_id TEXT NOT NULL REFERENCES companions(id),
    business_date TEXT NOT NULL,
    affinity_delta INTEGER NOT NULL DEFAULT 0 CHECK(affinity_delta >= 0),
    response_text TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(evidence_refs_json)),
    created_at INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX one_affinity_grant_per_day ON companion_interactions(companion_id,business_date) WHERE affinity_delta > 0;

CREATE TABLE achievement_grants (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    code TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    ledger_id TEXT REFERENCES ledger_entries(id),
    corrected_at INTEGER,
    created_at INTEGER NOT NULL,
    UNIQUE(owner_id,code)
) STRICT;

CREATE TABLE habit_plans (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    kind TEXT NOT NULL CHECK(kind IN ('checkin','screen_time','custom')),
    title TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    archived_at INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX one_special_habit ON habit_plans(owner_id,kind) WHERE kind IN ('checkin','screen_time') AND archived_at IS NULL;

CREATE TABLE habit_plan_revisions (
    plan_id TEXT NOT NULL REFERENCES habit_plans(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    effective_from TEXT NOT NULL,
    weekdays_json TEXT NOT NULL CHECK(json_valid(weekdays_json)),
    terms_json TEXT NOT NULL CHECK(json_valid(terms_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    created_at INTEGER NOT NULL,
    PRIMARY KEY(plan_id,revision)
) STRICT;
CREATE INDEX habit_revisions_effective ON habit_plan_revisions(plan_id,effective_from,revision);

CREATE TABLE habit_rest_days (
    plan_id TEXT NOT NULL REFERENCES habit_plans(id),
    business_date TEXT NOT NULL,
    declared_at INTEGER NOT NULL,
    PRIMARY KEY(plan_id,business_date)
) STRICT;

CREATE TABLE habit_occurrences (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    plan_id TEXT NOT NULL REFERENCES habit_plans(id),
    business_date TEXT NOT NULL,
    timezone_snapshot TEXT NOT NULL,
    terms_snapshot_json TEXT NOT NULL CHECK(json_valid(terms_snapshot_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    state TEXT NOT NULL CHECK(state IN ('due','completed','missed','rest','unknown')),
    completed_at INTEGER,
    startup_attempt_id TEXT REFERENCES card_attempts(id),
    screen_record_id TEXT REFERENCES screen_records(id),
    settlement_ledger_id TEXT REFERENCES ledger_entries(id),
    settled_at INTEGER,
    settlement_detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(settlement_detail_json)),
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(plan_id,business_date)
) STRICT;

CREATE TABLE screen_records (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    occurrence_id TEXT NOT NULL REFERENCES habit_occurrences(id),
    business_date TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    scope TEXT NOT NULL CHECK(scope IN ('entertainment','all_screen')),
    minutes INTEGER NOT NULL CHECK(minutes BETWEEN 0 AND 1440),
    note TEXT NOT NULL DEFAULT '',
    confirmed_at INTEGER NOT NULL,
    after_settlement INTEGER NOT NULL DEFAULT 0 CHECK(after_settlement IN (0,1)),
    UNIQUE(owner_id,business_date,revision)
) STRICT;

CREATE TABLE commitments (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    title TEXT NOT NULL,
    target_points INTEGER NOT NULL CHECK(target_points > 0),
    stake_coins INTEGER NOT NULL CHECK(stake_coins > 0),
    bonus_coins INTEGER NOT NULL CHECK(bonus_coins >= 0),
    terms_json TEXT NOT NULL CHECK(json_valid(terms_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    state TEXT NOT NULL CHECK(state IN ('proposed','active','pending_settlement','won','lost','voided','cancelled')),
    accepted_at INTEGER,
    accepted_business_date TEXT,
    deadline_at INTEGER NOT NULL,
    grace_deadline_at INTEGER NOT NULL,
    timezone_snapshot TEXT NOT NULL,
    settled_at INTEGER,
    settlement_ledger_id TEXT REFERENCES ledger_entries(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    CHECK(grace_deadline_at >= deadline_at)
) STRICT;
CREATE UNIQUE INDEX one_active_commitment ON commitments(owner_id) WHERE state IN ('active','pending_settlement');
CREATE UNIQUE INDEX one_daily_commitment_acceptance ON commitments(owner_id,accepted_business_date) WHERE accepted_at IS NOT NULL;
CREATE TRIGGER accepted_commitment_terms_immutable BEFORE UPDATE ON commitments
WHEN OLD.accepted_at IS NOT NULL AND (
    NEW.target_points IS NOT OLD.target_points OR NEW.stake_coins IS NOT OLD.stake_coins OR
    NEW.bonus_coins IS NOT OLD.bonus_coins OR NEW.terms_json IS NOT OLD.terms_json OR
    NEW.rule_version IS NOT OLD.rule_version OR NEW.accepted_at IS NOT OLD.accepted_at OR
    NEW.accepted_business_date IS NOT OLD.accepted_business_date OR
    NEW.deadline_at IS NOT OLD.deadline_at OR NEW.grace_deadline_at IS NOT OLD.grace_deadline_at OR
    NEW.timezone_snapshot IS NOT OLD.timezone_snapshot
)
BEGIN SELECT RAISE(ABORT,'accepted_terms_are_immutable'); END;

CREATE TABLE redemptions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    catalog_code TEXT NOT NULL REFERENCES catalog_items(code),
    price_coins INTEGER NOT NULL CHECK(price_coins >= 0),
    terms_snapshot_json TEXT NOT NULL CHECK(json_valid(terms_snapshot_json)),
    input_json TEXT NOT NULL CHECK(json_valid(input_json)),
    state TEXT NOT NULL CHECK(state IN ('reserved','running','needs_review','succeeded','failed','cancelled')),
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number > 0),
    provider_snapshot_json TEXT CHECK(provider_snapshot_json IS NULL OR json_valid(provider_snapshot_json)),
    rule_version TEXT NOT NULL REFERENCES rule_versions(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE generated_assets (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    redemption_id TEXT NOT NULL UNIQUE REFERENCES redemptions(id),
    kind TEXT NOT NULL CHECK(kind IN ('image','text')),
    relative_path TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
    prompt_summary TEXT NOT NULL,
    favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1,
    provider_metadata_json TEXT NOT NULL CHECK(json_valid(provider_metadata_json)),
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE story_series (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    title TEXT NOT NULL,
    bible_json TEXT NOT NULL CHECK(json_valid(bible_json)),
    bible_version INTEGER NOT NULL DEFAULT 1,
    rolling_summary TEXT NOT NULL DEFAULT '',
    last_completed_number INTEGER NOT NULL DEFAULT 0 CHECK(last_completed_number >= 0),
    version INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE story_chapters (
    id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL REFERENCES story_series(id),
    number INTEGER NOT NULL CHECK(number > 0),
    redemption_id TEXT NOT NULL UNIQUE REFERENCES redemptions(id),
    state TEXT NOT NULL CHECK(state IN ('pending','ready','failed')),
    context_snapshot_json TEXT NOT NULL CHECK(json_valid(context_snapshot_json)),
    title TEXT,
    body_md TEXT,
    summary TEXT,
    asset_id TEXT UNIQUE REFERENCES generated_assets(id),
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    UNIQUE(series_id,number)
) STRICT;
CREATE UNIQUE INDEX one_pending_story_chapter ON story_chapters(series_id) WHERE state = 'pending';

CREATE TABLE agent_threads (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    title TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(context_json)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;

CREATE TABLE agent_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES agent_threads(id),
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')),
    content_md TEXT NOT NULL,
    attachments_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(attachments_json)),
    run_id TEXT REFERENCES agent_runs(id),
    created_at INTEGER NOT NULL,
    UNIQUE(thread_id,sequence)
) STRICT;

CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    thread_id TEXT NOT NULL REFERENCES agent_threads(id),
    job_id TEXT REFERENCES jobs(id),
    state TEXT NOT NULL CHECK(state IN ('queued','running','waiting_input','succeeded','failed','cancelled')),
    prompt_version TEXT NOT NULL,
    provider_snapshot_json TEXT NOT NULL CHECK(json_valid(provider_snapshot_json)),
    context_snapshot_json TEXT NOT NULL CHECK(json_valid(context_snapshot_json)),
    usage_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(usage_json)),
    created_at INTEGER NOT NULL,
    completed_at INTEGER
) STRICT;

CREATE TABLE agent_tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    sequence INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL CHECK(json_valid(arguments_json)),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    command_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('proposed','executed','rejected')),
    created_at INTEGER NOT NULL,
    UNIQUE(run_id,sequence)
) STRICT;

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    job_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    state TEXT NOT NULL CHECK(state IN ('queued','running','retry_wait','needs_review','succeeded','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    available_at INTEGER NOT NULL,
    lease_owner TEXT,
    lease_until INTEGER,
    lease_token INTEGER NOT NULL DEFAULT 0,
    provider_request_id TEXT,
    external_request_started_at INTEGER,
    last_error_json TEXT CHECK(last_error_json IS NULL OR json_valid(last_error_json)),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
) STRICT;
CREATE INDEX jobs_ready ON jobs(state,available_at);

CREATE TABLE job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX events_job_order ON job_events(job_id,id);

CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    event_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    target_path TEXT NOT NULL,
    read_at INTEGER,
    created_at INTEGER NOT NULL,
    UNIQUE(owner_id,event_key)
) STRICT;

CREATE TABLE idempotency_keys (
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    route TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('processing','completed','failed')),
    http_status INTEGER,
    response_json TEXT CHECK(response_json IS NULL OR json_valid(response_json)),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY(owner_id,route,key)
) STRICT;

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('user','system','agent')),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    detail_json TEXT NOT NULL CHECK(json_valid(detail_json)),
    request_id TEXT,
    created_at INTEGER NOT NULL
) STRICT;

CREATE TABLE backup_records (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    relative_path TEXT,
    state TEXT NOT NULL CHECK(state IN ('queued','running','ready','failed')),
    manifest_json TEXT CHECK(manifest_json IS NULL OR json_valid(manifest_json)),
    sha256 TEXT,
    created_at INTEGER NOT NULL,
    completed_at INTEGER
) STRICT;

CREATE TABLE study_reports (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES profiles(id),
    period_kind TEXT NOT NULL CHECK(period_kind IN ('day','week')),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    content_md TEXT NOT NULL,
    source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json)),
    created_at INTEGER NOT NULL,
    UNIQUE(owner_id,period_kind,start_date,end_date,input_hash)
) STRICT;

-- FTS5 是可重建的搜索投影，正文和来源仍保存在业务表中。
CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    entity_type UNINDEXED,
    entity_id UNINDEXED,
    owner_id UNINDEXED,
    title,
    body,
    tokenize = 'trigram'
);
