"""分析用DBから学習データを取得する。

`bot/`には一切依存せず、`ml/db.py`（読み取り専用接続）のみを使う。
"""

import pandas as pd

import db

# 実施後アンケート（schedule_score）が紐づいた候補枠のみを学習データとして扱う。
# is_selected（=実際に選ばれた枠）以外は候補として提示されただけでアンケートに繋がらないため対象外。
_LABELED_SLOTS_QUERY = """
SELECT
    cs.id AS candidate_slot_id,
    cs.rank_order,
    cs.start_time,
    cs.score AS heuristic_score,
    a.duration_minutes,
    s.schedule_score
FROM one_on_one_candidate_slots cs
JOIN one_on_one_attempts a ON a.id = cs.attempt_id
JOIN one_on_one_events e ON e.candidate_slot_id = cs.id
JOIN one_on_one_surveys s ON s.event_id = e.id
WHERE s.schedule_score IS NOT NULL
"""


def count_labeled_slots():
    """モデル学習に使えるラベル付きデータ件数（schedule_scoreが記録済みのアンケート件数）。"""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM one_on_one_surveys WHERE schedule_score IS NOT NULL")
            return cur.fetchone()[0]


def fetch_labeled_slots():
    """schedule_scoreが紐づいた候補枠を学習データ（DataFrame）として取得する。"""
    with db.get_connection() as conn:
        return pd.read_sql(_LABELED_SLOTS_QUERY, conn)
