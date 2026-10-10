"""Cover subject-scoped learning totals without reading every ledger payload."""
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    op.get_bind().exec_driver_sql(
        "CREATE INDEX ledger_claim_learning ON ledger_entries(claim_id,owner_id,business_date,learning_delta)"
    )


def downgrade():
    raise RuntimeError("Use a verified backup to restore an earlier database")
