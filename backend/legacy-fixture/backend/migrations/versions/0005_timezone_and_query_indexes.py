"""Historical timezone semantics and indexes for bounded world/report queries."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        "CREATE TABLE profile_timezone_changes (id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES profiles(id),effective_date TEXT NOT NULL,previous_timezone TEXT NOT NULL,timezone TEXT NOT NULL,created_at INTEGER NOT NULL) STRICT",
        "CREATE INDEX timezone_owner_day ON profile_timezone_changes(owner_id,effective_date,created_at)",
        "CREATE INDEX plant_plot ON plants(plot_id,state)",
        "CREATE INDEX inventory_placed ON inventory_items(placed_plot_id,state)",
        "CREATE INDEX plot_point ON world_plots(point_id)",
        "CREATE INDEX attempts_activity ON card_attempts(activity_id)",
        "CREATE INDEX job_attempt ON jobs(kind,json_extract(payload_json,'$.attempt_id'),created_at)",
        "CREATE INDEX job_activity ON jobs(kind,json_extract(payload_json,'$.activity_id'),state)",
        "CREATE INDEX timers_owner_created ON timer_sessions(owner_id,created_at)",
    ]
    for statement in statements:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("请恢复已验证备份，不删除历史时区记录。")
