"""1on1スコアリングの補正値を計算するモデル。

実施後アンケート（`schedule_score`: 0〜5、「日程のレコメンドはいかがでしたか」の回答）が
`MIN_TRAINING_SAMPLES`件以上蓄積されたら、そのデータでモデルを学習し、
`bot/gcal/scheduler.py`のヒューリスティックなスコアに対する補正値（-1.0〜1.0）を計算する。

このモジュールは`bot/`を一切importせず、実際にbotのスコアリングへ組み込む呼び出しもまだ無い。
データが十分に溜まった段階で、モデルの評価・実運用への組み込み判断を別途行う想定。
"""

import logging

import pandas as pd
from sklearn.linear_model import LinearRegression

import data

logger = logging.getLogger(__name__)

MIN_TRAINING_SAMPLES = 1000

FEATURE_COLUMNS = ["heuristic_score", "rank_order", "duration_minutes", "hour", "weekday"]


def _normalize_schedule_score(schedule_score):
    """アンケートの0〜5スコアを、補正値と同じ-1.0〜1.0のスケールに正規化する。"""
    return (schedule_score - 2.5) / 2.5


def _build_features(df):
    df = df.copy()
    df["hour"] = df["start_time"].dt.hour
    df["weekday"] = df["start_time"].dt.weekday
    return df[FEATURE_COLUMNS]


def train_correction_model():
    """ラベル付きデータが`MIN_TRAINING_SAMPLES`件に満たない場合はNoneを返す。
    足りていれば学習データを取得しモデルを学習して返す（学習のみ行い、保存や適用は行わない）。"""
    labeled_count = data.count_labeled_slots()
    if labeled_count < MIN_TRAINING_SAMPLES:
        logger.info(
            f"学習データが{labeled_count}件のためモデル学習をスキップします（{MIN_TRAINING_SAMPLES}件必要）"
        )
        return None

    df = data.fetch_labeled_slots()
    features = _build_features(df)
    target = df["schedule_score"].apply(_normalize_schedule_score)

    model = LinearRegression()
    model.fit(features, target)
    return model


def compute_score_correction(model, heuristic_score, rank_order, duration_minutes, start_time):
    """学習済みモデルから、指定した候補枠のスコアリング補正値を計算する。
    戻り値は常に-1.0〜1.0にクリップする（元のヒューリスティックスコアへの掛け目として使う想定）。"""
    features = pd.DataFrame(
        [
            {
                "heuristic_score": heuristic_score,
                "rank_order": rank_order,
                "duration_minutes": duration_minutes,
                "hour": start_time.hour,
                "weekday": start_time.weekday(),
            }
        ]
    )
    correction = float(model.predict(features)[0])
    return max(-1.0, min(1.0, correction))
