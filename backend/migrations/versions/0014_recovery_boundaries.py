"""Preserve evidence time across explicit retries and meter live provider calls."""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE provider_calls ADD COLUMN provider_key TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE provider_calls ADD COLUMN lease_token INTEGER NOT NULL DEFAULT 0")
    op.execute("CREATE INDEX provider_calls_active ON provider_calls(owner_id,provider_key,state,completed_at)")
    op.execute("ALTER TABLE system_action_revisions ADD COLUMN evidence_cutoff_at INTEGER")
    op.execute("ALTER TABLE system_decisions ADD COLUMN review_code TEXT")


def downgrade():
    raise RuntimeError("Restore a verified backup; decision evidence must be preserved.")
