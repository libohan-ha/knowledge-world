"""Stable world-history append boundary and restore lineage; preserve old payloads."""

from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    for statement in [
        "CREATE TABLE world_history_state (id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL) STRICT",
        "INSERT INTO world_history_state(id,epoch) VALUES(1,lower(hex(randomblob(24))))",
        "CREATE TABLE world_event_order (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE REFERENCES world_events(id)) STRICT",
        "INSERT INTO world_event_order(event_id) SELECT id FROM world_events ORDER BY rowid",
        "CREATE INDEX world_history_owner_time ON world_events(owner_id,created_at,id)",
        "CREATE TRIGGER world_history_append AFTER INSERT ON world_events BEGIN INSERT INTO world_event_order(event_id) VALUES(NEW.id); END",
    ]:
        op.get_bind().exec_driver_sql(statement)
    for table in ('world_events', 'world_event_order'):
        for action in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'world history is append only'); END")


def downgrade():
    raise RuntimeError('World history is append only; restore a verified backup instead.')
