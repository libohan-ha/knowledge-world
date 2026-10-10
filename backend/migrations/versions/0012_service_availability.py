"""Record API availability so an outage cannot become a missed-checkin penalty."""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE service_availability (
        id TEXT PRIMARY KEY, process_id TEXT NOT NULL,
        started_at INTEGER NOT NULL, through_at INTEGER NOT NULL,
        CHECK(through_at>=started_at)) STRICT""")
    op.execute("CREATE INDEX availability_range ON service_availability(started_at,through_at)")
    op.execute("CREATE INDEX challenge_action ON system_challenges(action_id) WHERE action_id IS NOT NULL")


def downgrade():
    raise RuntimeError("Restore a verified backup; availability evidence must not be dropped.")
