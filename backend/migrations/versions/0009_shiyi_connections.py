"""Persist the user's explicit read-only Shiyi connection identity and settings."""
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade():
    op.get_bind().exec_driver_sql("""CREATE TABLE shiyi_connections (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL REFERENCES profiles(id),
        api_url TEXT NOT NULL,
        secret_ref TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
        version INTEGER NOT NULL DEFAULT 1 CHECK(version>=1),
        checked_at INTEGER,
        last_success_at INTEGER,
        last_error_code TEXT,
        capabilities_json TEXT NOT NULL DEFAULT '{}',
        retired_at INTEGER,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""")
    op.get_bind().exec_driver_sql("CREATE UNIQUE INDEX shiyi_one_current ON shiyi_connections(owner_id) WHERE retired_at IS NULL")


def downgrade():
    raise RuntimeError("Use a verified backup to restore an earlier database")
