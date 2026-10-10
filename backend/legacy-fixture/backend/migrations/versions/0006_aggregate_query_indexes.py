"""Indexes established from the measured 5k / 20k / 100k acceptance dataset."""
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    for statement in [
        "CREATE INDEX ledger_owner_time ON ledger_entries(owner_id,created_at DESC,id)",
        "CREATE INDEX ledger_owner_totals ON ledger_entries(owner_id,business_date,learning_delta,available_delta,held_delta,entry_type)",
        "CREATE INDEX card_point_active ON cards(point_id,state)",
        "CREATE INDEX assessment_owner_category ON assessments(owner_id,reward_category,state,claim_id,target_points)",
        "CREATE INDEX claim_owner_day ON learning_claims(owner_id,first_business_date,id)",
        "CREATE INDEX claim_point ON learning_claims(point_id,id)",
    ]:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Use a verified backup to restore an earlier database")
