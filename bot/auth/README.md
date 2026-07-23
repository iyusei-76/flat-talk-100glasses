# auth/ — Google認証まわり

Slackユーザーごとの Google OAuth 連携（認可・トークン保存・暗号化）を担当する。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `google_oauth.py` | OAuthフロー全体の中心。認可URL生成、CSRF対策のstate管理、コード⇔トークン交換、トークンの保存/読み込み（期限切れ時は自動リフレッシュ） |
| `oauth_callback_server.py` | Googleからのリダイレクト（`/oauth2callback`）を受けるFlaskサーバー。`app.py`から別スレッドで起動される |
| `token_store.py` | `google_credentials`テーブルへのCRUD（DBアクセスのみ、暗号化やGoogle API呼び出しは行わない） |
| `crypto_utils.py` | `GOOGLE_TOKEN_ENCRYPTION_KEY`を使ったFernetによるトークンの暗号化/復号 |

## 認証フローの流れ

1. Slack側（`slack/commands.py`の`?google_auth`など）が `google_oauth.create_authorization_url(slack_user_id)` を呼ぶ
   - state トークンを発行し、PKCEの `code_verifier` と紐付けてプロセス内メモリ（`_pending_states`）に保持（TTL 10分）
2. ユーザーがブラウザでGoogleの認可画面に遷移し、許可すると `oauth_callback_server.py` の `/oauth2callback` にリダイレクトされる
3. `google_oauth.resolve_state(state)` で state を検証・消費し、`exchange_code_for_credentials()` でトークンを取得
4. `google_oauth.save_credentials()` が `crypto_utils.encrypt()` で暗号化した上で `token_store.save_google_credentials()` によりDBへ保存
5. 以降のカレンダー操作（`gcal/`）は `google_oauth.load_credentials(slack_user_id)` で復号・必要ならリフレッシュしたCredentialsを取得して使う

## 注意点

- `_pending_states` はプロセス内メモリなので、プロセス再起動やマルチプロセス構成では state が失われる
- 必須環境変数: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` / `GOOGLE_TOKEN_ENCRYPTION_KEY`
