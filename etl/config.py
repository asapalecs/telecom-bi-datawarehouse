"""
Configurarea pipeline-ului. Orice setare poate fi suprascrisa prin variabile
de mediu. Motor: DW_ENGINE=sqlite (implicit) sau DW_ENGINE=sqlserver.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
SQL_DIR = PROJECT_ROOT / "sql"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


DW_ENGINE = os.getenv("DW_ENGINE", "sqlite").lower()

MSSQL_HOST = os.getenv("MSSQL_HOST", "localhost")
MSSQL_PORT = os.getenv("MSSQL_PORT", "1433")
MSSQL_DB = os.getenv("MSSQL_DB", "TelecomDW")
MSSQL_USER = os.getenv("MSSQL_USER", "sa")
MSSQL_PASSWORD = os.getenv("MSSQL_PASSWORD", "")
MSSQL_DRIVER = os.getenv("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", PROCESSED_DIR / "telecom_dw.db"))


def get_engine() -> Engine:
    if DW_ENGINE == "sqlserver":
        try:
            import pyodbc  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "DW_ENGINE=sqlserver necesita pyodbc, care nu este instalat.\n"
                "  Instalare:  pip install -r requirements-sqlserver.txt\n"
                "  Este necesar si driverul ODBC la nivel de sistem - vezi acel\n"
                "  fisier pentru instructiuni pe fiecare platforma.\n"
                "  Pentru rulare fara SQL Server:  DW_ENGINE=sqlite"
            ) from exc

        if not MSSQL_PASSWORD:
            raise RuntimeError(
                "MSSQL_PASSWORD nu este setat. Exporta-l sau foloseste DW_ENGINE=sqlite."
            )
        # URL.create escapeaza parola (caractere ca @ / : ar strica un URL scris manual).
        # TrustServerCertificate e necesar pentru certificatul self-signed din container.
        conn = URL.create(
            "mssql+pyodbc",
            username=MSSQL_USER, password=MSSQL_PASSWORD,
            host=MSSQL_HOST, port=int(MSSQL_PORT), database=MSSQL_DB,
            query={"driver": MSSQL_DRIVER, "TrustServerCertificate": "yes"},
        )
        return create_engine(conn, fast_executemany=True)

    return create_engine(f"sqlite:///{SQLITE_PATH}")


def is_sqlserver() -> bool:
    return DW_ENGINE == "sqlserver"


N_CUSTOMERS = int(os.getenv("N_CUSTOMERS", "5000"))
START_DATE = os.getenv("START_DATE", "2023-01-01")
END_DATE = os.getenv("END_DATE", "2025-12-31")

# Seed fix pentru rezultate reproductibile.
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))


def describe() -> str:
    target = (
        f"SQL Server {MSSQL_HOST}:{MSSQL_PORT}/{MSSQL_DB}"
        if is_sqlserver()
        else f"SQLite {SQLITE_PATH}"
    )
    return (
        f"Motor      : {DW_ENGINE}\n"
        f"Tinta      : {target}\n"
        f"Clienti    : {N_CUSTOMERS:,}\n"
        f"Perioada   : {START_DATE} - {END_DATE}\n"
        f"Seed       : {RANDOM_SEED}"
    )


if __name__ == "__main__":
    print(describe())
