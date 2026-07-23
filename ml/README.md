# ml/ — 1on1分析データを使った機械学習用コード

`bot/`（Slackボット本体）とは完全に分離された、機械学習の実験・学習用ディレクトリ。

## 分離方針

- `ml/`配下のコードは`bot/`配下のモジュールを一切importしない。両者の唯一の接点は、`bot/analytics/store.py`が書き込む分析用DBのテーブルスキーマのみ（詳細は[bot/analytics/README.md](../bot/analytics/README.md)を参照）。
- 依存関係（`requirements.txt`）もbotとは別に管理する。pandas/scikit-learn等のMLライブラリをbot側のDockerイメージに混在させない。
- DB接続コードもbot側の`db.py`を再利用せず、`ml/db.py`に最小限のものを別途用意している（数行の重複を許容し、import結合を作らないため）。

## 接続先

`ANALYTICS_DB_*`環境変数（未設定なら`DB_*`にフォールバック）でPostgresの分析用テーブルに接続する。ボット本体と同じルールなので、リポジトリ直下の`.env`をそのまま利用できる。

## データ契約（読み取り対象テーブル）

| テーブル | 内容 |
|---|---|
| `one_on_one_attempts` | 1on1候補提示1回分（スコアリング時のコンテキストスナップショット含む） |
| `one_on_one_candidate_slots` | 提示した候補枠ごとのスコア・順位・選ばれたか |
| `one_on_one_events` | 実際にカレンダー登録されたイベント |
| `one_on_one_surveys` | 実施後アンケート結果 |

## ディレクトリ構成

| ファイル | 役割 |
|---|---|
| `requirements.txt` | ML用の依存関係（bot/requirements.txtとは独立） |
| `db.py` | 分析用DBへの読み取り専用接続 |
| `data.py` | `one_on_one_surveys.schedule_score`が紐づいた候補枠を学習データとして取得 |
| `model.py` | 学習データが`MIN_TRAINING_SAMPLES`（1000）件以上あればモデルを学習し、スコアリング補正値（-1.0〜1.0）を計算する |
| `train.py` | 手動実行用エントリポイント（`python train.py`）。botやCIから自動では呼ばれない |

## スコアリング補正値について

`bot/gcal/scheduler.py`のヒューリスティックなスコアリングに対し、実施後アンケート（`schedule_score`:
「日程のレコメンドはいかがでしたか」への回答、0:忙しくて迷惑だった 〜 5:ちょうどよかった）を教師データとして
モデルを学習し、-1.0〜1.0の補正値を計算できるようにしたもの。

- `data.count_labeled_slots()` : 学習に使えるラベル付きデータ（アンケート回答済みの候補枠）件数を取得
- `model.train_correction_model()` : 件数が`MIN_TRAINING_SAMPLES`（1000）未満ならNoneを返す。以上あれば
  `LinearRegression`を学習して返す（0〜5のアンケートスコアを-1.0〜1.0に正規化して目的変数とする）
- `model.compute_score_correction(...)` : 学習済みモデルから、指定した候補枠の補正値を計算する（常に-1.0〜1.0にクリップ）

**現時点ではbot側のスコアリングにこの補正値を適用する呼び出しは無い。** データが十分に溜まって
モデルを学習できる状態になった段階で、モデルの精度評価・実運用への組み込み方針を別途検討する。

## 議論メモ（notes/）

`notes/`配下は、上記の`data.py`/`model.py`/`train.py`（現行の実装）とは完全に独立した、
将来のモデル検討用メモ・叩き台コードを置く場所。ここにあるコードはどこからもimportされない。

- [`notes/treebase_participation_model.py`](notes/treebase_participation_model.py) : 「先月/先週の空き状況」
  「前後の予定（ヒューリスティックスコアに反映済み）」「個人の趣向（アンケート回答者ごとの過去スコアの
  expanding mean）」を特徴量にしたtree系（GBDT）モデルの学習・補正値算出コード（2026-07-23の議論メモ、未検証）
