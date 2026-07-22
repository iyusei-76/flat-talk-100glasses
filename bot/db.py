import os

import psycopg2


def get_connection():
    """message_logs用の接続（DB_*を参照）"""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
    )


def get_auth_connection():
    """google_credentials / user_profiles用の接続（AUTH_DB_*があれば優先、無ければDB_*にフォールバック）"""
    return psycopg2.connect(
        host=os.environ.get("AUTH_DB_HOST", os.environ.get("DB_HOST", "db")),
        database=os.environ.get("AUTH_DB_NAME", os.environ.get("DB_NAME")),
        user=os.environ.get("AUTH_DB_USER", os.environ.get("DB_USER")),
        password=os.environ.get("AUTH_DB_PASSWORD", os.environ.get("DB_PASSWORD")),
    )
