# gcal/ — Googleカレンダー操作

Google Calendar APIを使った予定の取得・登録、および1on1向けの空き時間探索を担当する。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `calendar_client.py` | カレンダーAPIの薄いラッパー（予定一覧取得・予定作成）、`?set`コマンドの入力パース、予定の整形表示 |
| `scheduler.py` | 2人分の空き時間からスコアリングして1on1候補枠を算出するロジック |

## calendar_client.py

- `get_upcoming_events` / `create_event` : Google Calendar API（`events().list` / `events().insert`）の呼び出し。未認証時は `NotAuthenticatedError` を送出
- `parse_set_command` : `?set タイトル MM/DD HH:MM 所要分 [@メンション...]` の入力を解析（不正な入力は `InvalidEventInputError`）
- `format_events_message` : 取得した予定をSlack表示用テキストに整形
- `find_1on1_slot_candidates` / `is_1on1_slot_still_available` : `scheduler.py` への薄い委譲（循環import回避のため遅延importしている）

## scheduler.py（1on1候補枠のスコアリング）

`find_top_slots(requester_id, partner_id, duration_minutes, top_n)` が本体。流れ:

1. 明日以降、土日祝（`jpholiday`）を除いた `CANDIDATE_BUSINESS_DAYS`（8営業日）分の候補日を列挙
2. 両者の `freebusy` APIから忙しい時間帯を取得し、30分単位のスロットごとにbusyフラグを付与
3. 双方とも空いているスロットの組み合わせに対して以下の観点でスコアリング（`_score_candidate`）
   - 前後の枠が埋まっている枠は減点（隙間時間になるのを避ける）
   - 昼休憩（12:00〜13:00）に被る枠は減点
   - 前後に3時間以上連続するbusyブロックを作ってしまう枠は減点
   - 近い日付ほど加点（`PROXIMITY_BONUS_PER_DAY`）
4. 同じ日の枠は最良の1つに絞り、スコア上位 `top_n` 件を返す

候補提示からユーザーが選ぶまでにタイムラグがあるため、確定直前に `is_slot_still_available` で再チェックしてから登録する。

## 注意点

- ディレクトリ名を`calendar`ではなく`gcal`にしているのは、標準ライブラリの`calendar`モジュールとの衝突を避けるため
- タイムゾーンは一貫してJST（`calendar_client.JST`）で扱う
