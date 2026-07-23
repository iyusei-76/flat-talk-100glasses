import os
from contextlib import contextmanager

import psycopg2


@contextmanager
def get_connection():
    """message_logs用の接続（DB_*を参照）"""
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_auth_connection():
    """google_credentials / user_profiles用の接続（AUTH_DB_*があれば優先、無ければDB_*にフォールバック）"""
    conn = psycopg2.connect(
        host=os.environ.get("AUTH_DB_HOST", os.environ.get("DB_HOST", "db")),
        database=os.environ.get("AUTH_DB_NAME", os.environ.get("DB_NAME")),
        user=os.environ.get("AUTH_DB_USER", os.environ.get("DB_USER")),
        password=os.environ.get("AUTH_DB_PASSWORD", os.environ.get("DB_PASSWORD")),
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_analytics_connection():
    """1on1の分析用データ（スコアリング結果・実施状況・アンケート等）の接続。
    ANALYTICS_DB_*があれば優先、無ければDB_*にフォールバック（将来的に物理的に別DBへ切り出せるようにするため）。
    Slackのイベント処理スレッドから同期的に呼ばれるため、誤設定等で接続先に到達できない場合に
    ハンドラスレッドを長時間専有しないよう接続タイムアウトを設けている。"""
    conn = psycopg2.connect(
        host=os.environ.get("ANALYTICS_DB_HOST", os.environ.get("DB_HOST", "db")),
        database=os.environ.get("ANALYTICS_DB_NAME", os.environ.get("DB_NAME")),
        user=os.environ.get("ANALYTICS_DB_USER", os.environ.get("DB_USER")),
        password=os.environ.get("ANALYTICS_DB_PASSWORD", os.environ.get("DB_PASSWORD")),
        connect_timeout=5,
    )
    try:
        yield conn
    finally:
        conn.close()
