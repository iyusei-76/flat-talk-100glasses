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
3. 双方とも空いているスロットの組み合わせに対して以下の観点でスコアリング（`_score_candidate`、-10〜+10にクリップ）
   - 近い日付ほど加点（`PROXIMITY_BONUS_MAX`、最も近い営業日で最大、候補日リスト末尾で0）
   - 始業(9:30)・終業(18:30)に近い枠は減点（`EDGE_OF_DAY_PENALTY_MAX`、前後1時間以内が対象）
   - 前後どちらも空いている（孤立した）枠は加点（`ISOLATION_BONUS`）
   - 前後どちらかの枠が埋まっている枠は減点（`ADJACENT_BUSY_PENALTY`、隙間時間になるのを避ける）
   - 前後どちらかに2時間以上連続するbusyブロックを作ってしまう枠は減点（`CONTINUOUS_BLOCK_BASE_PENALTY`、超過分はさらに加算）
   - 昼休憩（12:00〜13:00）に被る枠、直後（13:00〜13:30）に被る枠はそれぞれ減点
   - 月曜・祝日明けの午前、金曜・祝日前の午後は減点（`DAY_TRANSITION_PENALTY`）
   - 当日15時以降にリクエストされた場合、翌日15:00までの枠は減点（`LATE_REQUEST_PENALTY`。相手への通知が直前すぎるのを避ける）
4. 同じ日の枠は最良の1つに絞り、スコア上位 `top_n` 件を返す

候補提示からユーザーが選ぶまでにタイムラグがあるため、確定直前に `is_slot_still_available` で再チェックしてから登録する。

`fetch_context_snapshot` は分析用データ（将来のML利用向け）に添える特徴量として、前7日間・先月同週の空き状況スナップショットを取得する（[analytics/README.md](../analytics/README.md)参照）。取得に失敗しても呼び出し元の処理は継続させるため例外は送出せずNoneを返す。

## 注意点

- ディレクトリ名を`calendar`ではなく`gcal`にしているのは、標準ライブラリの`calendar`モジュールとの衝突を避けるため
- タイムゾーンは一貫してJST（`calendar_client.JST`）で扱う
