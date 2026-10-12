"""User-defined repeatable tasks and immutable completion receipts."""
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE fixed_tasks (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id),
        title TEXT NOT NULL, description TEXT NOT NULL, reward_points INTEGER NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)''')
    op.execute('''CREATE TABLE fixed_task_completions (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES profiles(id),
        task_id TEXT NOT NULL REFERENCES fixed_tasks(id), completion_id TEXT NOT NULL,
        receipt_json TEXT NOT NULL, created_at INTEGER NOT NULL,
        UNIQUE(owner_id, completion_id))''')


def downgrade():
    raise RuntimeError('Restore a verified backup; completion history must be retained.')
