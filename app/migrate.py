"""Additive schema migrations, run on startup.

create_all() makes new tables but never adds columns to existing ones. This adds any
column a model has that the live table lacks (nullable, or with its scalar default),
so deploys that add fields never need a manual step. It never drops or alters data.
Swap for Alembic once schema changes stop being purely additive.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db import Base

log = logging.getLogger(__name__)


def _default_sql(col) -> str | None:
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return None
    v = d.arg
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return None


def add_missing_columns(engine: Engine) -> list[str]:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                default = _default_sql(col)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
                if default is not None:
                    ddl += f" DEFAULT {default}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    if added:
        log.info("added columns: %s", ", ".join(added))
    return added
