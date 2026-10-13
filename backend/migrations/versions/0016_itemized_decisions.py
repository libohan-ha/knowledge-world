"""Itemized system judgments: each self-report item keeps its own tier and receipt line."""
from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    # Older decisions remain single-item; an empty list means "judged as one action".
    op.execute("ALTER TABLE system_decisions ADD COLUMN items_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(items_json))")


def downgrade():
    raise RuntimeError('Restore a verified backup; decision history must be retained.')
