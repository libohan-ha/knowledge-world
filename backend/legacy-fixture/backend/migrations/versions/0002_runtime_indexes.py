"""Runtime call accounting, message identity, and query indexes."""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    statements = [
        "ALTER TABLE agent_messages ADD COLUMN client_message_id TEXT",
        "CREATE UNIQUE INDEX message_client_identity ON agent_messages(thread_id,client_message_id) WHERE client_message_id IS NOT NULL",
        "CREATE TABLE provider_calls (id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),owner_id TEXT NOT NULL REFERENCES profiles(id),role TEXT NOT NULL,model TEXT NOT NULL,started_at INTEGER NOT NULL,completed_at INTEGER,request_id TEXT,usage_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(usage_json)),state TEXT NOT NULL DEFAULT 'started') STRICT",
        "CREATE INDEX provider_calls_day ON provider_calls(owner_id,role,started_at)",
        "CREATE INDEX point_owner_subject ON knowledge_points(owner_id,subject_id,archived_at)",
        "CREATE INDEX activity_owner_day ON activities(owner_id,business_date,submitted_at)",
        "CREATE INDEX assessment_claim_cutoff ON assessments(claim_id,evidence_cutoff_at,revision)",
        "CREATE INDEX card_owner_point ON cards(owner_id,point_id,state)",
        "CREATE INDEX evidence_activity ON evidence_items(activity_id)",
        "CREATE INDEX plot_region ON world_plots(region_id,grid_y,grid_x)",
        "CREATE INDEX tasks_owner_state ON study_tasks(owner_id,state)",
        "CREATE INDEX habit_owner_day ON habit_occurrences(owner_id,business_date,settled_at)",
    ]
    for statement in statements:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("运行记录采用追加迁移，请通过备份恢复")
