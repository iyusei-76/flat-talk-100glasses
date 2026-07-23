"""[設計メモ / 未検証] Tree系（GBDT）モデルによる1on1スコアリング補正の将来案。

## 背景（2026-07-23の議論）

「先月スケジュール」「先週スケジュール」「前後の予定」から求まる参加確率的な特徴量と、
実施後アンケート（schedule_score）による個人の趣向を反映したモデルを作るなら、
tree系モデルと時系列モデル（RNN/Transformer等）のどちらが良いか、という議論の結論案。

- アンケート回答はデータ量が少なく（学習開始の目安は1000件規模）、回答者も限られるためラベルが疎
- カレンダーの予定は間隔が不規則（irregular）で、素直な等間隔の時系列データではない
- 個人の趣向は「ユーザーIDをそのまま特徴量に使う」「そのユーザーの過去のアンケート傾向を
  特徴量に混ぜる」といった手軽な方法でtree系モデルに組み込める
- 上記の理由から、時系列モデルよりtree系モデル（本メモではsklearnのHistGradientBoostingRegressor。
  依存関係を追加できるならLightGBM/XGBoostへの差し替えも容易）が優位という結論に基づく実装案

## 位置づけ

このファイルは`ml/data.py` / `ml/model.py` / `ml/train.py`（現行の実装）とは完全に独立しており、
どこからもimportしない・されない。DB接続も意図的に自己完結させている（`ml/db.py`との結合を作らないため）。
実際にbotのスコアリングへ組み込む想定はまだなく、将来モデルを検討する際の叩き台として置いてあるだけの
参考コード（実データでのスキーマ検証・精度検証は未実施）。

## 前提（未検証）

- `one_on_one_attempts.context_snapshot`に、`gcal/scheduler.fetch_context_snapshot()`が返す
  `{"requester": {...}, "partner": {...}}`形式（各々`prior_7_days` / `same_week_last_month`に
  `busy`区間リストを持つ）がそのまま保存されている前提で特徴量を組み立てている
"""

import os
from contextlib import contextmanager
from datetime import datetime

import pandas as pd
import psycopg2
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

MIN_TRAINING_SAMPLES = 1000

FEATURE_COLUMNS = [
    "heuristic_score",
    "rank_order",
    "duration_minutes",
    "hour",
    "weekday",
    "prior_week_busy_minutes",
    "prior_week_busy_count",
    "last_month_busy_minutes",
    "last_month_busy_count",
    "personal_bias",
]


@contextmanager
def _get_connection():
    """このメモ専用の読み取り接続。`ml/db.py`を使い回さず意図的に重複させている
    （`ml/README.md`にある「数行の重複を許容し、import結合を作らない」という本プロジェクトの方針に合わせた）。"""
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


_LABELED_ROWS_QUERY = """
SELECT
    cs.rank_order,
    cs.start_time,
    cs.score AS heuristic_score,
    a.duration_minutes,
    a.requester_id,
    a.partner_id,
    a.context_snapshot,
    s.slack_user_id AS respondent_id,
    s.schedule_score,
    s.submitted_at
FROM one_on_one_candidate_slots cs
JOIN one_on_one_attempts a ON a.id = cs.attempt_id
JOIN one_on_one_events e ON e.candidate_slot_id = cs.id
JOIN one_on_one_surveys s ON s.event_id = e.id
WHERE s.schedule_score IS NOT NULL
ORDER BY s.submitted_at
"""


def _fetch_labeled_rows():
    with _get_connection() as conn:
        return pd.read_sql(_LABELED_ROWS_QUERY, conn)


def _busy_density(context_snapshot, side, window_key):
    """context_snapshot（JSONB）から、指定した側（requester/partner）・期間
    （prior_7_days / same_week_last_month）のbusy時間合計（分）と区間数を取り出す。
    取得できない場合は(0.0, 0)を返す。"""
    if not context_snapshot:
        return 0.0, 0

    side_snapshot = context_snapshot.get(side)
    if not side_snapshot:
        return 0.0, 0

    window = side_snapshot.get(window_key)
    if not window:
        return 0.0, 0

    intervals = window.get("busy", [])
    total_minutes = sum(
        (datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds() / 60
        for start_iso, end_iso in intervals
    )
    return total_minutes, len(intervals)


def _respondent_side(row):
    """アンケート回答者が、候補提示時のrequester/partnerのどちら側だったかを返す。"""
    return "requester" if row["respondent_id"] == row["requester_id"] else "partner"


def _personal_bias_features(df):
    """個人の趣向（ファインチューニング用特徴量）: そのユーザーが過去に提出したアンケートスコアの
    累積平均を、各行の時点より前の回答だけを使うexpanding meanとして計算する（リーク防止）。
    初回回答（過去データが無い）は全体平均で埋める。df は submitted_at 昇順である前提。"""
    global_mean = df["schedule_score"].mean()

    personal_bias = []
    history = {}
    for _, row in df.iterrows():
        past_scores = history.setdefault(row["respondent_id"], [])
        personal_bias.append(sum(past_scores) / len(past_scores) if past_scores else global_mean)
        past_scores.append(row["schedule_score"])

    return personal_bias


def _build_features(df):
    df = df.sort_values("submitted_at").reset_index(drop=True).copy()
    df["hour"] = df["start_time"].apply(lambda t: t.hour)
    df["weekday"] = df["start_time"].apply(lambda t: t.weekday())
    df["respondent_side"] = df.apply(_respondent_side, axis=1)

    prior_week_minutes, prior_week_count = [], []
    last_month_minutes, last_month_count = [], []
    for _, row in df.iterrows():
        w_min, w_cnt = _busy_density(row["context_snapshot"], row["respondent_side"], "prior_7_days")
        m_min, m_cnt = _busy_density(row["context_snapshot"], row["respondent_side"], "same_week_last_month")
        prior_week_minutes.append(w_min)
        prior_week_count.append(w_cnt)
        last_month_minutes.append(m_min)
        last_month_count.append(m_cnt)

    df["prior_week_busy_minutes"] = prior_week_minutes
    df["prior_week_busy_count"] = prior_week_count
    df["last_month_busy_minutes"] = last_month_minutes
    df["last_month_busy_count"] = last_month_count
    df["personal_bias"] = _personal_bias_features(df)

    return df[FEATURE_COLUMNS], df["schedule_score"]


def _normalize_schedule_score(schedule_score):
    """アンケートの0〜5スコアを、補正値と同じ-1.0〜1.0のスケールに正規化する。"""
    return (schedule_score - 2.5) / 2.5


def train():
    """学習データを取得し、GBDT（HistGradientBoostingRegressor）を学習して返す。
    件数不足の場合はNoneを返す。ホールドアウト評価のMAEも表示する（あくまで動作確認用）。"""
    df = _fetch_labeled_rows()
    if len(df) < MIN_TRAINING_SAMPLES:
        print(f"学習データが{len(df)}件のため学習をスキップします（{MIN_TRAINING_SAMPLES}件必要）")
        return None

    features, raw_target = _build_features(df)
    target = raw_target.apply(_normalize_schedule_score)

    X_train, X_test, y_train, y_test = train_test_split(features, target, test_size=0.2, random_state=0)

    model = HistGradientBoostingRegressor()
    model.fit(X_train, y_train)

    mae = mean_absolute_error(y_test, model.predict(X_test))
    print(f"ホールドアウトMAE: {mae:.3f}（学習データ{len(df)}件中、テスト{len(X_test)}件で評価）")

    return model


def compute_score_correction(model, feature_row):
    """学習済みモデルから、指定した候補枠1件分の補正値を計算する。
    feature_row: FEATURE_COLUMNSと同じキーを持つ1件分のdict。戻り値は常に-1.0〜1.0にクリップする。"""
    row_df = pd.DataFrame([feature_row])[FEATURE_COLUMNS]
    correction = float(model.predict(row_df)[0])
    return max(-1.0, min(1.0, correction))


if __name__ == "__main__":
    train()
