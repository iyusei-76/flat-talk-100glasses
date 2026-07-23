"""1on1の分析用データ（スコアリング結果・実施状況・アンケート）の保存。

将来の機械学習利用を見据えたログ用モジュールであり、既存の1on1フローの動作には
一切影響してはならない。そのため全ての公開関数は例外を握りつぶし、失敗時は
ログを出して何もせず戻る（呼び出し側でtry/exceptを書く必要はない）。
"""

import logging
import threading

from psycopg2.extras import Json

import db

logger = logging.getLogger(__name__)

_schema_ready = False
_schema_lock = threading.Lock()

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS one_on_one_attempts (
        id SERIAL PRIMARY KEY,
        requester_id VARCHAR(50) NOT NULL,
        partner_id VARCHAR(50) NOT NULL,
        duration_minutes INTEGER NOT NULL,
        context_snapshot JSONB,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS one_on_one_candidate_slots (
        id SERIAL PRIMARY KEY,
        attempt_id INTEGER NOT NULL REFERENCES one_on_one_attempts(id),
        rank_order INTEGER NOT NULL,
        start_time TIMESTAMP WITH TIME ZONE NOT NULL,
        end_time TIMESTAMP WITH TIME ZONE NOT NULL,
        score NUMERIC NOT NULL,
        is_selected BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS one_on_one_events (
        id SERIAL PRIMARY KEY,
        candidate_slot_id INTEGER REFERENCES one_on_one_candidate_slots(id),
        requester_id VARCHAR(50) NOT NULL,
        partner_id VARCHAR(50) NOT NULL,
        google_event_id TEXT,
        original_start TIMESTAMP WITH TIME ZONE NOT NULL,
        original_end TIMESTAMP WITH TIME ZONE NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'scheduled'
            CHECK (status IN ('scheduled', 'rescheduled', 'cancelled', 'held', 'no_show')),
        last_checked_start TIMESTAMP WITH TIME ZONE,
        last_checked_end TIMESTAMP WITH TIME ZONE,
        last_checked_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS one_on_one_surveys (
        id SERIAL PRIMARY KEY,
        event_id INTEGER NOT NULL REFERENCES one_on_one_events(id),
        slack_user_id VARCHAR(50) NOT NULL,
        held BOOLEAN,
        feedback TEXT,
        submitted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


def _ensure_schema(conn):
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with conn.cursor() as cur:
            for statement in _SCHEMA_STATEMENTS:
                cur.execute(statement)
        conn.commit()
        _schema_ready = True


def record_attempt(requester_id, partner_id, duration_minutes, context_snapshot=None):
    """1on1候補提示（スコアリング）1回分を記録し、attempt_idを返す。失敗時はNoneを返す。"""
    try:
        with db.get_analytics_connection() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO one_on_one_attempts
                        (requester_id, partner_id, duration_minutes, context_snapshot)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        requester_id,
                        partner_id,
                        duration_minutes,
                        Json(context_snapshot) if context_snapshot is not None else None,
                    ),
                )
                attempt_id = cur.fetchone()[0]
            conn.commit()
        return attempt_id
    except Exception:
        logger.warning(
            f"1on1分析データ(attempt)の記録に失敗しました ({requester_id}/{partner_id})", exc_info=True
        )
        return None


def record_candidate_slots(attempt_id, candidates):
    """candidates: [{"start": datetime, "end": datetime, "score": number}, ...]（スコア降順）"""
    if attempt_id is None:
        return
    try:
        with db.get_analytics_connection() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                for rank_order, candidate in enumerate(candidates, start=1):
                    cur.execute(
                        """
                        INSERT INTO one_on_one_candidate_slots
                            (attempt_id, rank_order, start_time, end_time, score)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (attempt_id, rank_order, candidate["start"], candidate["end"], candidate["score"]),
                    )
            conn.commit()
    except Exception:
        logger.warning(
            f"1on1分析データ(candidate_slots)の記録に失敗しました (attempt_id={attempt_id})", exc_info=True
        )


def mark_selected_and_record_event(requester_id, partner_id, start, end, google_event_id):
    """選ばれた候補枠にis_selectedを立て、実際にカレンダー登録されたイベントを記録し、event_idを返す。
    対応するcandidate_slotが見つからなくても、イベント自体はcandidate_slot_id=NULLで記録する。失敗時はNoneを返す。"""
    try:
        with db.get_analytics_connection() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cs.id
                    FROM one_on_one_candidate_slots cs
                    JOIN one_on_one_attempts a ON a.id = cs.attempt_id
                    WHERE a.requester_id = %s AND a.partner_id = %s
                      AND cs.start_time = %s AND cs.end_time = %s
                    ORDER BY a.created_at DESC
                    LIMIT 1
                    """,
                    (requester_id, partner_id, start, end),
                )
                row = cur.fetchone()
                candidate_slot_id = row[0] if row else None

                if candidate_slot_id is not None:
                    cur.execute(
                        "UPDATE one_on_one_candidate_slots SET is_selected = TRUE WHERE id = %s",
                        (candidate_slot_id,),
                    )

                cur.execute(
                    """
                    INSERT INTO one_on_one_events
                        (candidate_slot_id, requester_id, partner_id, google_event_id, original_start, original_end)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (candidate_slot_id, requester_id, partner_id, google_event_id, start, end),
                )
                event_id = cur.fetchone()[0]
            conn.commit()
        return event_id
    except Exception:
        logger.warning(
            f"1on1分析データ(event)の記録に失敗しました ({requester_id}/{partner_id})", exc_info=True
        )
        return None


def update_event_status(event_id, status, checked_start=None, checked_end=None):
    """予定の変更/キャンセル検知など、後日のポーリング処理からの呼び出しを想定（未実装の呼び出し元向けに用意）。"""
    try:
        with db.get_analytics_connection() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE one_on_one_events
                    SET status = %s, last_checked_start = %s, last_checked_end = %s,
                        last_checked_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, checked_start, checked_end, event_id),
                )
            conn.commit()
    except Exception:
        logger.warning(
            f"1on1分析データ(event status)の更新に失敗しました (event_id={event_id})", exc_info=True
        )


def record_survey(event_id, slack_user_id, held, feedback=None):
    """実施後アンケート結果の記録（未実装の送信フロー向けに用意）。"""
    try:
        with db.get_analytics_connection() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO one_on_one_surveys (event_id, slack_user_id, held, feedback)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (event_id, slack_user_id, held, feedback),
                )
            conn.commit()
    except Exception:
        logger.warning(f"1on1分析データ(survey)の記録に失敗しました (event_id={event_id})", exc_info=True)
