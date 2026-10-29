"""
LOAD - incarca schema stea in baza tinta: dimensiunile inaintea faptelor,
indecsii dupa incarcarea masiva, apoi view-urile KPI.
"""

from __future__ import annotations

import logging
import re

import pandas as pd
from sqlalchemy import inspect, text

from config import PROCESSED_DIR, SQL_DIR, get_engine, is_sqlserver

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("load")

# Ordinea conteaza pentru integritatea referentiala.
LOAD_ORDER = [
    "dim_date",
    "dim_plan",
    "dim_geography",
    "dim_channel",
    "dim_customer",
    "fact_subscription_monthly",
]

INDEXES = [
    ("ix_fact_date", "fact_subscription_monthly", "date_key"),
    ("ix_fact_customer", "fact_subscription_monthly", "customer_key"),
    ("ix_fact_plan", "fact_subscription_monthly", "plan_key"),
    ("ix_fact_geo", "fact_subscription_monthly", "geography_key"),
    ("ix_fact_channel", "fact_subscription_monthly", "channel_key"),
    ("ix_dim_customer_current", "dim_customer", "is_current"),
    ("ix_dim_customer_natural", "dim_customer", "customer_id"),
    ("ix_dim_date_ym", "dim_date", "year_month"),
]


def clear_existing(engine) -> None:
    """Pe SQL Server goleste tabelele create de create_tables.sql in loc sa le
    stearga: un DROP ar esua pe FK-uri si ar pierde columnstore-ul."""
    existing = set(n.lower() for n in inspect(engine).get_table_names())
    with engine.begin() as conn:
        for name in reversed(LOAD_ORDER):
            if name in existing:
                conn.execute(text(f"DELETE FROM {name}"))


def load_table(engine, name: str) -> int:
    df = pd.read_csv(PROCESSED_DIR / f"{name}.csv")
    df.to_sql(
        name,
        engine,
        if_exists="append" if is_sqlserver() else "replace",
        index=False,
        chunksize=1000,
        method="multi" if not is_sqlserver() else None,
    )
    log.info("  %-30s %7d randuri", name, len(df))
    return len(df)


def create_indexes(engine) -> None:
    created = 0
    with engine.begin() as conn:
        for idx_name, table, column in INDEXES:
            try:
                conn.execute(text(f"CREATE INDEX {idx_name} ON {table} ({column})"))
                created += 1
            except Exception as exc:
                if "already exists" not in str(exc).lower():
                    log.warning("  index %s: %s", idx_name, str(exc).splitlines()[0])
    log.info("  %d indecsi creati", created)


def _tsql_to_sqlite(sql: str) -> str:
    """Traduce T-SQL-ul din views.sql in dialectul SQLite."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

    # `IF OBJECT_ID('dbo.V_X', 'V') IS NOT NULL DROP VIEW dbo.V_X;` -> `DROP VIEW IF EXISTS V_X;`
    sql = re.sub(
        r"IF\s+OBJECT_ID\(\s*'(?:dbo\.)?(\w+)'\s*,\s*'V'\s*\)\s+IS\s+NOT\s+NULL\s+"
        r"DROP\s+VIEW\s+(?:dbo\.)?\w+\s*;?",
        r"DROP VIEW IF EXISTS \1;",
        sql,
        flags=re.IGNORECASE,
    )

    sql = re.sub(r"\bdbo\.", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^\s*GO\s*$", ";", sql, flags=re.IGNORECASE | re.MULTILINE)
    sql = sql.replace("ISNULL(", "IFNULL(")

    return sql


def create_views(engine) -> None:
    view_sql = (SQL_DIR / "views.sql").read_text(encoding="utf-8")

    if is_sqlserver():
        # CREATE VIEW trebuie sa fie singur in batch, deci se executa pe batch-uri GO.
        view_sql = re.sub(r"/\*.*?\*/", "", view_sql, flags=re.DOTALL)
        statements = [s.strip() for s in re.split(r"^\s*GO\s*$", view_sql,
                                                  flags=re.IGNORECASE | re.MULTILINE)]
    else:
        statements = [s.strip() for s in _tsql_to_sqlite(view_sql).split(";")]

    created, failed = 0, 0
    with engine.begin() as conn:
        for stmt in filter(None, statements):
            head = stmt.upper().lstrip()
            if not head.startswith(("CREATE VIEW", "DROP VIEW", "IF OBJECT_ID")):
                continue
            try:
                conn.execute(text(stmt))
                if head.startswith("CREATE"):
                    created += 1
            except Exception as exc:
                failed += 1
                name = re.search(r"VIEW\s+(?:IF\s+EXISTS\s+)?(\w+)", stmt, re.I)
                log.error("  view %s a esuat: %s",
                          name.group(1) if name else "?",
                          str(exc).splitlines()[0][:140])

    expected = len(re.findall(r"^\s*CREATE\s+VIEW\b", view_sql, re.I | re.M))
    if failed or created != expected:
        raise RuntimeError(
            f"View-uri create {created}/{expected}, {failed} esuate - stratul KPI este incomplet."
        )
    log.info("  %d view-uri create", created)


def verify(engine) -> None:
    """Reciteste datele din baza si raporteaza numarul de randuri si KPI-urile."""
    log.info("Verificare date incarcate...")
    with engine.connect() as conn:
        for name in LOAD_ORDER:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            log.info("  %-30s %7d randuri", name, n)

        kpi = conn.execute(text("""
            SELECT
                COUNT(DISTINCT customer_id)                        AS customers,
                SUM(total_revenue)                                 AS revenue,
                SUM(total_revenue) / COUNT(*)                      AS arpu,
                CAST(SUM(CAST(is_churn AS INT)) AS FLOAT) / COUNT(*) * 100 AS churn_pct,
                CAST(SUM(complaint_count) AS FLOAT) / COUNT(*) * 100 AS complaint_pct
            FROM fact_subscription_monthly
        """)).fetchone()

    log.info("KPI principali din depozit:")
    log.info("  Clienti distincti  : %s", f"{kpi[0]:,}")
    log.info("  Venit total        : %s RON", f"{kpi[1]:,.2f}")
    log.info("  ARPU               : %.2f RON/luna", kpi[2])
    log.info("  Rata churn         : %.2f %% pe luna", kpi[3])
    log.info("  Rata reclamatii    : %.2f %% pe abonat-luna", kpi[4])


def main() -> None:
    engine = get_engine()
    log.info("Incarcare schema stea in %s...", engine.url.render_as_string(hide_password=True))

    if is_sqlserver():
        clear_existing(engine)

    total = 0
    for name in LOAD_ORDER:
        total += load_table(engine, name)

    log.info("Creare indecsi...")
    create_indexes(engine)

    log.info("Creare view-uri analitice...")
    create_views(engine)

    verify(engine)
    log.info("Load finalizat - %d randuri in total.", total)


if __name__ == "__main__":
    main()
