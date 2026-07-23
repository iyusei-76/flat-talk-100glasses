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

## ディレクトリ構成（雛形）

| ファイル | 役割 |
|---|---|
| `requirements.txt` | ML用の依存関係（bot/requirements.txtとは独立） |
| `db.py` | 分析用DBへの読み取り専用接続 |
