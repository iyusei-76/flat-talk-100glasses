# analytics/ — 1on1分析用データ（将来のML利用向け）

1on1のスコアリング結果・実施状況・アンケート結果を、既存の運用DBとは別枠のテーブル群に記録する。
将来的にこのデータを機械学習（例: スコアリングモデルの改善、実施率の予測など）に使うことを想定している。

## 設計方針

- **既存の1on1フローの動作には一切影響させない。** `store.py`の全公開関数は内部で例外を握りつぶし、失敗時はログを出してNone/no-opを返すだけにしている。呼び出し側でtry/exceptを書く必要はなく、分析DBが落ちていてもSlack上の1on1フローは通常通り進む
- 接続先は`db.get_analytics_connection()`（`ANALYTICS_DB_*`環境変数、未設定なら`DB_*`にフォールバック）。`auth/token_store.py`が`AUTH_DB_*`を使うのと同じパターンで、将来的に物理的に別DBへ切り出せるようにしている
- テーブルは`store.py`の各関数が初回呼び出し時に`CREATE TABLE IF NOT EXISTS`で自動作成する（`db/init.sql`にも新規構築用に同じ定義を追加済み）

## ファイル構成

| ファイル | 役割 |
|---|---|
| `store.py` | スキーマ定義と記録関数一式 |

## テーブル

| テーブル | 内容 |
|---|---|
| `one_on_one_attempts` | 1on1候補提示（スコアリング）1回分。`context_snapshot`に前7日間・先月同週の空き状況スナップショットをJSONBで保存 |
| `one_on_one_candidate_slots` | 提示した候補枠ごとのスコア・順位・実際に選ばれたか |
| `one_on_one_events` | 実際にGoogleカレンダーへ登録されたイベント（元の日時・ステータス） |
| `one_on_one_surveys` | 実施後アンケート結果 |

## 現状の記録フロー

- `slack/one_on_one.py`の`_post_slot_candidates`（候補日時提示時）→ `record_attempt` + `record_candidate_slots`
  - `context_snapshot`は`gcal/scheduler.fetch_context_snapshot()`で取得（前7日間 / 先月同週=4週間前の週の空き状況）
- `slack/one_on_one.py`の`handle_select_1on1_slot`（カレンダー登録確定時）→ `mark_selected_and_record_event`

## 未実装（今後の拡張ポイント）

以下は`store.py`に受け皿の関数だけ用意してあり、実際に呼び出す仕組みはまだない。設計判断（送信タイミング・文言・ポーリング方式など）が別途必要。

- `update_event_status` : 予定の変更/キャンセルを検知するポーリング処理（Google Calendar `events().get()`で`status`/`start`/`end`を再取得する想定）
- `record_survey` : 実施後アンケートの送信・回収フロー
