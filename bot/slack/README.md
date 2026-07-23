# slack/ — Slackイベント処理・文言

Slack Bolt を使ったイベント/アクションのハンドラと、ユーザーへの見せ方（文言・Block Kit）を担当する。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `bolt_app.py` | Boltの `App` インスタンス生成。各ハンドラモジュールはここから`app`をimportして共有する |
| `messages.py` | 全てのSlack文言・Block Kitテンプレート集約。業務ロジック（DB検索・Google連携・カレンダー操作）は持たない |
| `commands.py` | DMの `message` イベント全般のルーティング。固定応答・`?ping`/`?data`/`?google_auth`/`?check`/`?set`/`?survey` |
| `profile_registration.py` | 「登録する」ボタン → プロフィール登録モーダルの表示・送信処理 |
| `one_on_one.py` | 1on1のカテゴリ選択 → 候補者提示 → 候補日時提示 → カレンダー登録までの一連のアクションハンドラ。実施後アンケート（`?survey`）の提示・回答記録も含む |

## commands.py のルーティング

`handle_im_messages` が全DMメッセージを受け、以下の順で処理する。

1. 全メッセージを`message_logs`にDB記録
2. 「自分で設定する」フロー中（`one_on_one._pending_manual_partners`）ならメンション入力として処理
3. 固定応答コマンド（`messages.STATIC_COMMANDS`）
4. `?ping` / `?data`（動作確認・DB最新5件表示）
5. `?google_auth`（Google連携開始）
6. `?check`（本日〜明日の予定確認）
7. `?set ...`（予定登録、`gcal/calendar_client.parse_set_command`に委譲）
8. `?survey`（終了時刻を過ぎた1on1のうち未回答の日程アンケートを1件提示、`one_on_one.post_next_pending_survey`に委譲）
9. 上記以外：未連携ならGoogle連携を促し、連携済みなら不明コマンド扱い

## one_on_one.py の状態遷移

1. `open_1on1_category_selection` : カテゴリ選択ボタンを表示
2. `select_1on1_category-*` : `profiles/profile_store`から候補を検索し、ランダムに最大3名提示
3. `select_1on1_partner-*` : `gcal/calendar_client.find_1on1_slot_candidates`で候補日時を3件提示
4. `select_1on1_slot-*` : 選択直前に空き状況を再チェック（`is_1on1_slot_still_available`）してからカレンダーに登録し、双方へ通知
5. `manual_1on1_partner` : ランダム抽選ではなく相手を`@`メンションで直接指定するフロー（`_pending_manual_partners`に入力待ちユーザーを保持し、`try_handle_pending_manual_partner`が`commands.py`から呼ばれる）

## 実施後アンケート（?survey）

- `post_next_pending_survey` : `analytics_store.get_pending_schedule_surveys`で終了時刻を過ぎた1on1のうち
  未回答のものを直近終了順に取得し、先頭の1件を「日程のレコメンドはいかがでしたか」の0〜5スコアボタンとして提示する
- `survey_score-*` : スコアボタン押下時、`analytics_store.record_survey`で回答（`schedule_score`）を記録する。
  実施有無をカレンダー側で検知する仕組みは無く、回答をもって実施済みとみなす（`held=True`固定）

## 注意点

- `_pending_manual_partners`（`one_on_one.py`）と`auth/google_oauth.py`の`_pending_states`はいずれもプロセス内メモリで、プロセス再起動で失われる
- action_idにユーザーIDやカテゴリ値を埋め込んでいるボタン（`select_1on1_category-*`など）は正規表現（`re.compile`）でマッチさせている
