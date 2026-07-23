# profiles/ — プロフィール / 1on1マッチング

ユーザーの入社年度・新卒/中途区分の保存と、1on1相手候補の検索条件判定を担当する。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `profile_store.py` | `user_profiles`テーブルへのCRUDと、カテゴリ別の候補ユーザー検索 |

## 主な関数

- `current_fiscal_year()` : 日本の会計年度（4月始まり）基準の「今の年度」を返す
- `save_user_profile` / `get_user_profile` : 入社年度・区分（`new_grad` / `mid_career`）の保存・取得
- `set_accepts_invitations(slack_user_id, accepts)` : 1on1候補としての招待を受け付けるか（`accepts_invitations`）を更新する。
  `slack/commands.py`の`?invite_pause` / `?invite_resume`コマンドから呼ばれる
- `get_candidate_slack_user_ids(category, current_fiscal_year_value, exclude_user_id=None)` : カテゴリ別に1on1候補を検索
  - `new_grad` : 今年度に入社した新卒
  - `mid_career` : 勤続2年未満の中途入社者
  - `existing` : 新卒は勤続1年以上、中途は勤続2年以上の既存社員
  - `any` : カテゴリで絞り込まず登録済み全員
  - いずれのカテゴリでも `accepts_invitations = TRUE`（招待を一時停止していない）のユーザーのみが対象

検索結果は `slack/one_on_one.py` の候補提示フローで利用される。

## 招待の受付停止

- `user_profiles.accepts_invitations`（デフォルト`TRUE`）が`FALSE`のユーザーは、カテゴリ抽選の候補から除外される（`profile_store.get_candidate_slack_user_ids`のWHERE句で常にフィルタされる）
- プロフィール未登録（`user_profiles`に行が無い）の場合は`?invite_pause`/`?invite_resume`を送ってもUPDATE対象が無く無視される。そのためコマンド側でプロフィール登録済みかを事前にチェックしている
