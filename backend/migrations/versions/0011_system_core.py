"""Append the system/game domain without rewriting legacy balances or terms."""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        "ALTER TABLE ledger_entries ADD COLUMN economic_kind TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE ledger_entries ADD COLUMN correction_of TEXT REFERENCES ledger_entries(id)",
        """CREATE TABLE core_transitions (
            owner_id TEXT PRIMARY KEY REFERENCES profiles(id), rule_version TEXT NOT NULL REFERENCES rule_versions(id),
            before_json TEXT NOT NULL CHECK(json_valid(before_json)), created_at INTEGER NOT NULL) STRICT""",
        """CREATE TABLE game_catalogs (
            version TEXT PRIMARY KEY REFERENCES rule_versions(id), payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
            created_at INTEGER NOT NULL) STRICT""",
        """CREATE TABLE heroes (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE REFERENCES profiles(id),
            strength INTEGER NOT NULL, agility INTEGER NOT NULL, mana INTEGER NOT NULL,
            training_steps INTEGER NOT NULL DEFAULT 0 CHECK(training_steps>=0),
            version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL) STRICT""",
        """CREATE TABLE monsters (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), species_code TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1 CHECK(level>=1), grant_key TEXT NOT NULL,
            rule_version TEXT NOT NULL REFERENCES rule_versions(id), version INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(owner_id,grant_key)) STRICT""",
        """CREATE TABLE teams (
            owner_id TEXT PRIMARY KEY REFERENCES profiles(id), member_ids_json TEXT NOT NULL CHECK(json_valid(member_ids_json)),
            version INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL) STRICT""",
        """CREATE TABLE home_items (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), code TEXT NOT NULL, name TEXT NOT NULL,
            kind TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1, x INTEGER, z INTEGER, rotation INTEGER NOT NULL DEFAULT 0,
            footprint INTEGER NOT NULL DEFAULT 1, grant_key TEXT NOT NULL, legacy_ref_json TEXT CHECK(json_valid(legacy_ref_json)),
            rule_version TEXT NOT NULL REFERENCES rule_versions(id), version INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(owner_id,grant_key),
            CHECK((x IS NULL AND z IS NULL) OR (x IS NOT NULL AND z IS NOT NULL))) STRICT""",
        """CREATE TABLE game_orders (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), quote_nonce TEXT NOT NULL,
            operation TEXT NOT NULL, target_id TEXT, price_points INTEGER NOT NULL CHECK(price_points>=0),
            rule_version TEXT NOT NULL REFERENCES rule_versions(id), receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
            created_at INTEGER NOT NULL, UNIQUE(owner_id,quote_nonce)) STRICT""",
        """CREATE TABLE game_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
            owner_id TEXT NOT NULL REFERENCES profiles(id), source_key TEXT NOT NULL, kind TEXT NOT NULL,
            object_id TEXT, region_id TEXT, origin_type TEXT NOT NULL, origin_id TEXT NOT NULL,
            before_json TEXT CHECK(json_valid(before_json)), after_json TEXT CHECK(json_valid(after_json)),
            receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)), rule_version TEXT NOT NULL REFERENCES rule_versions(id),
            business_date TEXT NOT NULL, timezone_snapshot TEXT NOT NULL, created_at INTEGER NOT NULL,
            UNIQUE(owner_id,source_key)) STRICT""",
        "CREATE INDEX game_history_owner_date ON game_events(owner_id,business_date,sequence)",
        "CREATE INDEX game_history_owner_kind ON game_events(owner_id,kind,sequence)",
        """CREATE TABLE battles (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), outpost_id TEXT NOT NULL,
            rule_version TEXT NOT NULL REFERENCES rule_versions(id), catalog_version TEXT NOT NULL REFERENCES game_catalogs(version),
            seed TEXT NOT NULL, engine_version TEXT NOT NULL, snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
            state TEXT NOT NULL CHECK(state IN ('queued','resolved')), job_id TEXT REFERENCES jobs(id),
            result_json TEXT CHECK(json_valid(result_json)), command_key TEXT NOT NULL,
            created_at INTEGER NOT NULL, completed_at INTEGER, UNIQUE(owner_id,command_key)) STRICT""",
        """CREATE TABLE occupations (
            owner_id TEXT NOT NULL REFERENCES profiles(id), outpost_id TEXT NOT NULL,
            battle_id TEXT NOT NULL REFERENCES battles(id), created_at INTEGER NOT NULL,
            PRIMARY KEY(owner_id,outpost_id)) STRICT""",
        """CREATE TABLE reward_catalog (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), code TEXT NOT NULL,
            name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price_points INTEGER NOT NULL CHECK(price_points>=0),
            duration_minutes INTEGER NOT NULL CHECK(duration_minutes>0), enabled INTEGER NOT NULL DEFAULT 1,
            version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            UNIQUE(owner_id,code)) STRICT""",
        """CREATE TABLE leisure_tickets (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), catalog_id TEXT NOT NULL REFERENCES reward_catalog(id),
            snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), rule_version TEXT NOT NULL REFERENCES rule_versions(id),
            price_points INTEGER NOT NULL CHECK(price_points>=0), duration_seconds INTEGER NOT NULL CHECK(duration_seconds>0),
            used_seconds INTEGER NOT NULL DEFAULT 0 CHECK(used_seconds>=0), quote_nonce TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('reserved','running','paused','completed','cancelled')),
            first_started_at INTEGER, running_since INTEGER, version INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(owner_id,quote_nonce)) STRICT""",
        "CREATE UNIQUE INDEX leisure_one_running ON leisure_tickets(owner_id) WHERE state='running'",
        """CREATE TABLE leisure_intervals (
            id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES leisure_tickets(id), started_at INTEGER NOT NULL,
            ended_at INTEGER, UNIQUE(ticket_id,started_at)) STRICT""",
        """CREATE TABLE system_actions (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), source_key TEXT NOT NULL,
            source_kind TEXT NOT NULL CHECK(source_kind IN ('self_report','skill')), source_json TEXT NOT NULL CHECK(json_valid(source_json)),
            message_id TEXT REFERENCES agent_messages(id), first_submitted_at INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'submitted', net_points INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            UNIQUE(owner_id,source_key)) STRICT""",
        """CREATE TABLE system_action_revisions (
            id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES system_actions(id), owner_id TEXT NOT NULL REFERENCES profiles(id),
            revision INTEGER NOT NULL, content TEXT NOT NULL, evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
            created_at INTEGER NOT NULL, UNIQUE(action_id,revision)) STRICT""",
        """CREATE TABLE system_decisions (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), action_id TEXT NOT NULL REFERENCES system_actions(id),
            action_version INTEGER NOT NULL, proposed_points INTEGER NOT NULL, approved_points INTEGER NOT NULL DEFAULT 0,
            applied_delta INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL, basis TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('proposed','applied','needs_review','rejected')),
            supersedes_id TEXT REFERENCES system_decisions(id), ledger_id TEXT REFERENCES ledger_entries(id),
            evidence_cutoff_at INTEGER NOT NULL, rule_version TEXT NOT NULL REFERENCES rule_versions(id),
            model_info_json TEXT NOT NULL CHECK(json_valid(model_info_json)), business_date TEXT, timezone_snapshot TEXT,
            created_at INTEGER NOT NULL, applied_at INTEGER, UNIQUE(action_id,action_version)) STRICT""",
        "CREATE INDEX system_decisions_day ON system_decisions(owner_id,business_date,state)",
        "CREATE INDEX system_actions_submission ON system_actions(owner_id,first_submitted_at)",
        """CREATE TABLE system_challenges (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), title TEXT NOT NULL, goal TEXT NOT NULL,
            reward_points INTEGER NOT NULL, penalty_points INTEGER NOT NULL DEFAULT 0, penalty_condition TEXT NOT NULL DEFAULT '',
            deadline_at INTEGER, rule_version TEXT NOT NULL REFERENCES rule_versions(id), terms_json TEXT NOT NULL CHECK(json_valid(terms_json)),
            state TEXT NOT NULL CHECK(state IN ('proposed','accepted','completed','failed','cancelled','needs_review')),
            action_id TEXT REFERENCES system_actions(id), accepted_at INTEGER, resolved_at INTEGER,
            version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL) STRICT""",
        """CREATE TABLE system_penalty_rules (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), title TEXT NOT NULL, condition TEXT NOT NULL,
            points INTEGER NOT NULL CHECK(points>=0), effective_date TEXT NOT NULL, disabled_at INTEGER,
            rule_version TEXT NOT NULL REFERENCES rule_versions(id), created_at INTEGER NOT NULL) STRICT""",
        """CREATE TABLE skill_settings (
            owner_id TEXT NOT NULL REFERENCES profiles(id), skill TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(owner_id,skill)) STRICT""",
        """CREATE TABLE legacy_contract_facts (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id), contract_id TEXT NOT NULL REFERENCES commitments(id),
            activity_id TEXT NOT NULL REFERENCES activities(id), fact_key TEXT NOT NULL, created_at INTEGER NOT NULL,
            UNIQUE(owner_id,fact_key)) STRICT""",
        """CREATE TRIGGER battle_snapshot_immutable BEFORE UPDATE ON battles WHEN
            NEW.snapshot_json IS NOT OLD.snapshot_json OR NEW.seed IS NOT OLD.seed OR NEW.outpost_id IS NOT OLD.outpost_id OR
            NEW.rule_version IS NOT OLD.rule_version OR NEW.catalog_version IS NOT OLD.catalog_version OR NEW.engine_version IS NOT OLD.engine_version OR
            (OLD.state='resolved' AND (NEW.state IS NOT OLD.state OR NEW.result_json IS NOT OLD.result_json))
            BEGIN SELECT RAISE(ABORT,'battle_snapshot_is_immutable'); END""",
        """CREATE TRIGGER applied_decision_immutable BEFORE UPDATE ON system_decisions WHEN OLD.state='applied'
            BEGIN SELECT RAISE(ABORT,'applied_decision_is_immutable'); END""",
    ]
    for statement in statements:
        op.get_bind().exec_driver_sql(statement)
    for table in ("game_events", "game_orders", "game_catalogs", "system_action_revisions"):
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_game_record'); END")


def downgrade():
    raise RuntimeError("Restore a verified pre-migration backup; game history must not be dropped.")
