import os
from contextlib import contextmanager

import psycopg2


@contextmanager
def get_connection():
    """分析用DBへの読み取り専用接続（ANALYTICS_DB_*、無ければDB_*にフォールバック）。
    bot/db.pyとは独立した実装（ml/はbot/に一切依存しない）。"""
    conn = psycopg2.connect(
        host=os.environ.get("ANALYTICS_DB_HOST", os.environ.get("DB_HOST", "localhost")),
        database=os.environ.get("ANALYTICS_DB_NAME", os.environ.get("DB_NAME")),
        user=os.environ.get("ANALYTICS_DB_USER", os.environ.get("DB_USER")),
        password=os.environ.get("ANALYTICS_DB_PASSWORD", os.environ.get("DB_PASSWORD")),
    )
    try:
        yield conn
    finally:
        conn.close()
