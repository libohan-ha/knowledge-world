"""Initial contract, frozen from docs/contracts/schema.sql."""

from pathlib import Path
import sqlite3
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    statement = ""
    for line in (Path(__file__).parent / "0001_schema.sql").read_text(encoding="utf-8").splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            op.get_bind().exec_driver_sql(statement)
            statement = ""


def downgrade():
    raise RuntimeError("初始业务数据不可降级删除，请恢复备份")
