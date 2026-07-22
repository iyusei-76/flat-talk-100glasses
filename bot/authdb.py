import os
import logging

import psycopg2

logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("AUTH_DB_HOST", os.environ.get("DB_HOST", "db")),
        database=os.environ.get("AUTH_DB_NAME", os.environ.get("DB_NAME")),
        user=os.environ.get("AUTH_DB_USER", os.environ.get("DB_USER")),
        password=os.environ.get("AUTH_DB_PASSWORD", os.environ.get("DB_PASSWORD")),
    )


def check_connection():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    return True


def save_google_credentials(slack_user_id, access_token_enc, refresh_token_enc, token_expiry, scope):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO google_credentials
                    (slack_user_id, access_token, refresh_token, token_expiry, scope, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (slack_user_id) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, google_credentials.refresh_token),
                    token_expiry = EXCLUDED.token_expiry,
                    scope = EXCLUDED.scope,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (slack_user_id, access_token_enc, refresh_token_enc, token_expiry, scope),
            )
        conn.commit()


def get_google_credentials(slack_user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT access_token, refresh_token, token_expiry, scope
                FROM google_credentials
                WHERE slack_user_id = %s
                """,
                (slack_user_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "token_expiry": row[2],
        "scope": row[3],
    }


def has_google_credentials(slack_user_id):
    return get_google_credentials(slack_user_id) is not None
