# flat-talk-100glasses

社内Slackワークスペース向けの1on1（ネットワーキング目的の対話）相手探し・日程調整ボット。

## できること

- カテゴリ（新卒 / 中途 / 既存社員 / 指定しない）を選ぶと、条件に合う社員をランダムに最大3名提示
- 提示された相手とのGoogleカレンダーの空き状況を突き合わせ、ヒューリスティックなスコアリングで1on1候補日時を提示（[bot/gcal/README.md](bot/gcal/README.md)参照）
- 候補から選ぶ、または日付・時刻をモーダルで直接指定してGoogleカレンダーに実登録（Google Meetリンク付き）。招待された相手には、カレンダー招待が実際に届いている場合に限り「都合が悪ければカレンダーから辞退してよい」旨をDMで案内
- `?set` コマンドで1on1に限らない任意の予定もカレンダーに登録可能（`@メンション`で招待も付与）
- 実施後アンケート（`?survey`）で「日程レコメンドの満足度」を収集し、将来的なスコアリング改善のための学習データとして蓄積（[ml/README.md](ml/README.md)参照）
- `?invite_pause` / `?invite_resume` で1on1候補としての招待を一時停止・再開

## 動作環境

- 言語 / フレームワーク: Python、[Slack Bolt](https://slack.dev/bolt-python/)（Socket Mode）
- DB: PostgreSQL 15
- 外部連携: Slack API（Bot Token / App Token）、Google Calendar API（OAuth2）
- インフラ: Docker Compose（`bot` / `db` の2コンテナ）

## セットアップ

1. `.env.example` を `.env` にコピーし、以下を埋める
   - `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`（Socket Mode対応のSlackアプリのトークン）
   - `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`
   - `GOOGLE_TOKEN_ENCRYPTION_KEY`（`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` で生成）
2. `docker compose up -d --build`
3. 初回起動時は `db/init.sql` が自動適用される。既存ボリュームに対する後続のスキーマ変更は自動適用されないため、`db/migrations/` 配下を手動適用する（各ファイル冒頭にコマンド例を記載）

---

## bot/ ディレクトリ構成

関心事ごとにディレクトリを分割している。ロジック自体は変更しておらず、配置の整理のみ。

```text
bot/
├── app.py                 # 薄いエントリーポイント（App起動・スレッド起動のみ）
├── db.py                  # 共通DB接続（message_logs用 / auth用の2種類）
├── health_checks.py       # 起動時のDB / Slack / Google疎通チェック
├── auth/                  # 認証まわり
│   ├── crypto_utils.py
│   ├── google_oauth.py         # Google OAuthフロー
│   ├── oauth_callback_server.py # OAuthコールバック受信用Flaskサーバー
│   └── token_store.py          # google_credentials テーブルCRUD
├── analytics/             # 1on1の分析用データ（将来のML利用向け）
│   └── store.py           # スコアリング結果・実施状況・アンケートの記録（既存フローには影響させない）
├── gcal/                  # カレンダー設定まわり
│   ├── calendar_client.py # Google Calendar API呼び出し + ?set入力解析 + 1on1予定の実登録
│   └── scheduler.py       # 1on1候補枠のスコアリング + 分析用コンテキストスナップショット取得
├── profiles/              # プロフィール / 1on1マッチングまわり
│   └── profile_store.py   # user_profiles テーブルCRUD・候補検索・年度計算・招待受付停止フラグ
└── slack/                 # Slack用の文言・ハンドラ
    ├── bolt_app.py              # Boltの App インスタンス（各ハンドラモジュールで共有）
    ├── messages.py              # 全てのSlack文言・Block Kitテンプレート
    ├── commands.py              # message イベント & ?ping/?help/?start/?data/?google_auth/?check/?set/?survey/?invite_pause/?invite_resume
    ├── profile_registration.py  # 「登録する」ボタン・プロフィール登録モーダル
    └── one_on_one.py            # 1on1のカテゴリ選択・候補提示・日時選択・カレンダー実登録・実施後アンケート
```

### 分割の考え方

- [`auth/`](bot/auth/README.md) : Google認証トークンの取得・保存・暗号化
- [`analytics/`](bot/analytics/README.md) : 1on1のスコアリング結果・実施状況・アンケートの記録（将来のML利用向け）
- [`gcal/`](bot/gcal/README.md) : Googleカレンダーに対する実際の操作（予定取得・登録）
- [`profiles/`](bot/profiles/README.md) : 入社年度・新卒/中途などユーザー属性の保存とマッチング条件の判定
- [`slack/`](bot/slack/README.md) : Slackへの見せ方（文言・Block Kit）とイベント/アクションのハンドラ

各ディレクトリの詳細は上記リンク先のサブREADMEを参照。

### 補足

- `calendar`というディレクトリ名は標準ライブラリの`calendar`モジュールと衝突する可能性があるため`gcal/`にしている。
- Dockerfileは`COPY *.py .`だとサブディレクトリがビルドに含まれないため`COPY . .`に変更済み。
