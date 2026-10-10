"""Persist catch-up cursor and the answer's business date, independent of later timezone edits."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE habit_plans ADD COLUMN materialized_through TEXT")
    op.execute("ALTER TABLE card_attempts ADD COLUMN answer_business_date TEXT")
    op.execute("ALTER TABLE card_attempts ADD COLUMN answer_timezone TEXT")
    op.execute("CREATE INDEX ix_material_chunk_confirmed ON material_chunks(material_id,confirmed_at)")


def downgrade():
    raise RuntimeError(
        "This migration preserves learning history; restore a verified backup instead of downgrading."
    )
