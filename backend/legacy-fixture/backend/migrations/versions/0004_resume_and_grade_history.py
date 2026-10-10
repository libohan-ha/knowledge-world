"""Persist resumable message context and append-only grading corrections."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        "ALTER TABLE agent_messages ADD COLUMN context_refs_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(context_refs_json))",
        "ALTER TABLE card_attempts ADD COLUMN requested_rating TEXT CHECK(requested_rating IN ('hard','good','easy'))",
        "UPDATE card_attempts SET requested_rating=rating WHERE rating IN ('hard','good','easy')",
        "CREATE TABLE attempt_gradings (id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES profiles(id),attempt_id TEXT NOT NULL REFERENCES card_attempts(id),revision INTEGER NOT NULL,correctness TEXT NOT NULL CHECK(correctness IN ('correct','incorrect','uncertain')),explanation_md TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '',model_info_json TEXT NOT NULL CHECK(json_valid(model_info_json)),created_at INTEGER NOT NULL,UNIQUE(attempt_id,revision)) STRICT",
        "CREATE TABLE review_corrections (id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES profiles(id),card_id TEXT NOT NULL REFERENCES cards(id),attempt_id TEXT NOT NULL REFERENCES card_attempts(id),grading_id TEXT NOT NULL UNIQUE REFERENCES attempt_gradings(id),before_json TEXT NOT NULL CHECK(json_valid(before_json)),after_json TEXT NOT NULL CHECK(json_valid(after_json)),replayed_events_json TEXT NOT NULL CHECK(json_valid(replayed_events_json)),created_at INTEGER NOT NULL) STRICT",
        "CREATE INDEX grade_attempt ON attempt_gradings(attempt_id,revision)",
        "CREATE INDEX correction_card ON review_corrections(card_id,created_at)",
        "CREATE INDEX card_attempt_day ON card_attempts(card_id,answer_business_date,answered_at)",
    ]
    for statement in statements:
        op.get_bind().exec_driver_sql(statement)
    for table in ("attempt_gradings", "review_corrections", "review_events"):
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'history is append only'); END"
            )


def downgrade():
    raise RuntimeError("学习历史只通过追加迁移维护；请恢复已验证备份。")
