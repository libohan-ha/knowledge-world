"""Pin the fact boundary even when submission and acceptance share a millisecond."""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE wager_acceptance_boundaries (
        contract_id TEXT PRIMARY KEY REFERENCES commitments(id),
        ledger_sequence INTEGER NOT NULL,
        same_instant_action_ids_json TEXT NOT NULL CHECK(json_valid(same_instant_action_ids_json))) STRICT""")


def downgrade():
    raise RuntimeError("Restore a verified backup; accepted fact boundaries must be preserved.")
