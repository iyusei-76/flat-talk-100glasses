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
| `one_on_one_surveys` | 実施後アンケート結果。`schedule_score`が「日程のレコメンドはいかがでしたか」の回答（0:忙しくて迷惑だった 〜 5:ちょうどよかった） |

## 現状の記録フロー

- `slack/one_on_one.py`の`_post_slot_candidates`（候補日時提示時）→ `record_attempt` + `record_candidate_slots`
  - `context_snapshot`は`gcal/scheduler.fetch_context_snapshot()`で取得（前7日間 / 先月同週=4週間前の週の空き状況）
- `slack/one_on_one.py`の`handle_select_1on1_slot`（カレンダー登録確定時）→ `mark_selected_and_record_event`
- `slack/one_on_one.py`の`?survey`コマンド（`post_next_pending_survey`）→ `get_pending_schedule_surveys`で終了時刻を過ぎた未回答の1on1を1件提示し、
  スコアボタン押下時（`handle_survey_score`）→ `record_survey`で`schedule_score`を記録
  - 「実施済みかどうか」はカレンダー側のポーリングでは検知していない。終了時刻を過ぎていて`status != 'cancelled'`であれば
    ユーザー自身の回答をもって実施済みとみなす（`held`は常に`True`で記録）

## 未実装（今後の拡張ポイント）

- `update_event_status` : 予定の変更/キャンセルを検知するポーリング処理（Google Calendar `events().get()`で`status`/`start`/`end`を再取得する想定）。
  受け皿の関数のみ用意してあり、実際に呼び出す仕組みはまだない
- `get_pending_schedule_surveys`は他の公開関数と異なり例外を握りつぶさない（`?survey`から能動的に呼ばれる読み取り専用の問い合わせで、
  失敗時は呼び出し側でユーザーにエラー表示する必要があるため）。書き込み系（`record_survey`など）は引き続き例外を握りつぶす方針のまま
