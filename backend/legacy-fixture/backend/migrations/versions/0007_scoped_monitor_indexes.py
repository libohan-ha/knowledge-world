"""Cover subject-scoped history and due-point queries measured in TC054."""
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    for statement in [
        "DROP INDEX ledger_owner_totals",
        "CREATE INDEX ledger_owner_totals ON ledger_entries(owner_id,business_date,claim_id,learning_delta,available_delta,held_delta,entry_type)",
        "DROP INDEX card_point_active",
        "CREATE INDEX card_point_active ON cards(point_id,state,id)",
        "CREATE INDEX point_scope_lookup ON knowledge_points(owner_id,subject_id,id)",
    ]:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    raise RuntimeError("Use a verified backup to restore an earlier database")
