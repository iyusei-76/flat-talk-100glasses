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
        schedule_score INTEGER CHECK (schedule_score BETWEEN 0 AND 5),
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


def record_survey(event_id, slack_user_id, held, feedback=None, schedule_score=None):
    """実施後アンケート結果の記録（`slack/one_on_one.py`の`?survey`回答ハンドラから呼ばれる）。

    schedule_score: 「日程のレコメンドはいかがでしたか」の回答（0:忙しくて迷惑だった 〜 5:ちょうどよかった）。
    """
    try:
        with db.get_analytics_connection() as conn:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO one_on_one_surveys (event_id, slack_user_id, held, feedback, schedule_score)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (event_id, slack_user_id, held, feedback, schedule_score),
                )
            conn.commit()
    except Exception:
        logger.warning(f"1on1分析データ(survey)の記録に失敗しました (event_id={event_id})", exc_info=True)


_PENDING_SURVEY_WHERE = """
    (e.requester_id = %(user_id)s OR e.partner_id = %(user_id)s)
    AND e.original_end < CURRENT_TIMESTAMP
    AND e.status != 'cancelled'
    AND NOT EXISTS (
        SELECT 1 FROM one_on_one_surveys s
        WHERE s.event_id = e.id AND s.slack_user_id = %(user_id)s AND s.schedule_score IS NOT NULL
    )
"""


def get_pending_schedule_surveys(slack_user_id, limit=5):
    """終了時刻を過ぎた（実施されたと思われる）1on1のうち、このユーザーがまだ
    日程レコメンドのスコアを回答していないものを、終了時刻が近い順に返す。

    他の公開関数と異なり、ここでは例外を握りつぶさない。`?survey`コマンドやHomeタブから
    能動的に呼ばれる読み取り専用の問い合わせであり、失敗時は呼び出し側でユーザーへの
    表示（エラー表示、またはHomeタブでの非表示扱い）を判断する必要があるため。
    """
    with db.get_analytics_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    e.id,
                    CASE WHEN e.requester_id = %(user_id)s THEN e.partner_id ELSE e.requester_id END,
                    e.original_start,
                    e.original_end
                FROM one_on_one_events e
                WHERE {_PENDING_SURVEY_WHERE}
                ORDER BY e.original_end ASC
                LIMIT %(limit)s
                """,
                {"user_id": slack_user_id, "limit": limit},
            )
            rows = cur.fetchall()

    return [
        {"event_id": row[0], "other_user_id": row[1], "start": row[2], "end": row[3]}
        for row in rows
    ]


def count_pending_schedule_surveys(slack_user_id):
    """`get_pending_schedule_surveys`と同条件の件数のみを返す（Homeタブでの表示用）。
    例外は握りつぶさない（呼び出し側で表示可否を判断する）。"""
    with db.get_analytics_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM one_on_one_events e WHERE {_PENDING_SURVEY_WHERE}",
                {"user_id": slack_user_id},
            )
            return cur.fetchone()[0]


def get_upcoming_events(slack_user_id, limit=5):
    """開始前（まだ実施していない）の確定済み1on1を、開始が近い順に返す（Homeタブでの表示用）。
    例外は握りつぶさない（呼び出し側で表示可否を判断する）。"""
    with db.get_analytics_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.id,
                    CASE WHEN e.requester_id = %(user_id)s THEN e.partner_id ELSE e.requester_id END,
                    e.original_start,
                    e.original_end
                FROM one_on_one_events e
                WHERE (e.requester_id = %(user_id)s OR e.partner_id = %(user_id)s)
                  AND e.original_start > CURRENT_TIMESTAMP
                  AND e.status != 'cancelled'
                ORDER BY e.original_start ASC
                LIMIT %(limit)s
                """,
                {"user_id": slack_user_id, "limit": limit},
            )
            rows = cur.fetchall()

    return [
        {"event_id": row[0], "other_user_id": row[1], "start": row[2], "end": row[3]}
        for row in rows
    ]
