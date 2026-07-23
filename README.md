# bot/ ディレクトリ構成

関心事ごとにディレクトリを分割している。ロジック自体は変更しておらず、配置の整理のみ。

```
bot/
├── app.py                 # 薄いエントリーポイント（App起動・スレッド起動のみ）
├── db.py                  # 共通DB接続（message_logs用 / auth用の2種類）
├── health_checks.py       # 起動時のDB / Slack / Google疎通チェック
├── auth/                  # 認証まわり
│   ├── crypto_utils.py
│   ├── google_oauth.py         # (旧 google_auth.py) Google OAuthフロー
│   ├── oauth_callback_server.py # (旧 oauth_server.py) OAuthコールバック受信用Flaskサーバー
│   └── token_store.py          # (旧 authdb.py の一部) google_credentials テーブルCRUD
├── analytics/             # 1on1の分析用データ（将来のML利用向け）
│   └── store.py           # スコアリング結果・実施状況・アンケートの記録（既存フローには影響させない）
├── gcal/                  # カレンダー設定まわり
│   ├── calendar_client.py # Google Calendar API呼び出し + ?set入力解析 + ダミー1on1予定作成
│   └── scheduler.py       # 1on1候補枠のスコアリング + 分析用コンテキストスナップショット取得
├── profiles/              # プロフィール / 1on1マッチングまわり
│   └── profile_store.py   # (旧 authdb.py の一部) user_profiles テーブルCRUD・候補検索・年度計算
└── slack/                 # Slack用の文言・ハンドラ
    ├── bolt_app.py              # Boltの App インスタンス（各ハンドラモジュールで共有）
    ├── messages.py              # 全てのSlack文言・Block Kitテンプレート
    ├── commands.py              # message イベント & ?ping/?data/?google_auth/?check/?set
    ├── profile_registration.py  # 「登録する」ボタン・プロフィール登録モーダル
    └── one_on_one.py            # 1on1のカテゴリ選択・候補提示・スケジュール（ダミー）
```

## 分割の考え方

- [`auth/`](bot/auth/README.md) : Google認証トークンの取得・保存・暗号化
- [`analytics/`](bot/analytics/README.md) : 1on1のスコアリング結果・実施状況・アンケートの記録（将来のML利用向け）
- [`gcal/`](bot/gcal/README.md) : Googleカレンダーに対する実際の操作（予定取得・登録）
- [`profiles/`](bot/profiles/README.md) : 入社年度・新卒/中途などユーザー属性の保存とマッチング条件の判定
- [`slack/`](bot/slack/README.md) : Slackへの見せ方（文言・Block Kit）とイベント/アクションのハンドラ

各ディレクトリの詳細は上記リンク先のサブREADMEを参照。

## 補足

- 旧`authdb.py`は「認証（google_credentials）」と「プロフィール/マッチング（user_profiles）」という別々の関心事が同居していたため、`auth/token_store.py`と`profiles/profile_store.py`に分割した。
- `calendar`というディレクトリ名は標準ライブラリの`calendar`モジュールと衝突する可能性があるため`gcal/`にしている。
- Dockerfileは`COPY *.py .`だとサブディレクトリがビルドに含まれないため`COPY . .`に変更済み。
