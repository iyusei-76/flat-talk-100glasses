# NNWS Slack Bot – セットアップ手順（Windowsデスクトップ常設サーバー版）

Slack DM経由でGoogleカレンダーの予定確認・登録ができるBotです。本READMEは、開発機から「家のWindowsデスクトップ」へ移植し、常設サーバーとして稼働させるための手順をまとめたものです（Cloudflare Tunnelで外部公開する構成・デモ用途）。



## 全体構成

- `bot/` : Slack Bolt (Socket Mode) + Flask（Google OAuthコールバック受信用、ポート8080）
- `db/` : PostgreSQL（メッセージログ・Google認証トークン保存）
- Slack本体との通信はSocket Mode（アウトバウンドのみ）のため公開ポートは不要
- Google OAuthのコールバックだけは外部（他メンバーのブラウザ）から届く必要があるため、Cloudflare Tunnelで一時的に公開URLを発行する

---

## 1. 前提: Windowsに必要なものを入れる

### 1-1. Git for Windows

1. https://git-scm.com/download/win からインストーラーをダウンロードして実行
2. インストール中の設定はデフォルトのままでOK
3. 確認:
   ```powershell
   git --version
   ```

### 1-2. Docker Desktop for Windows

1. https://www.docker.com/products/docker-desktop/ からインストーラーをダウンロード
2. インストール時に「Use WSL 2 instead of Hyper-V」を選択（推奨）
3. インストール後、一度PCを再起動
4. スタートメニューから **Docker Desktop** を起動し、システムトレイのクジラアイコンが「Running」になるまで待つ
5. 確認:

   ```powershell
   docker --version
   docker compose version
   ```

6. **自動アップデートを無効化する**（常設サーバー化のため）: Docker Desktopの設定画面（歯車アイコン）→ **General** → 「**Automatically check for updates**」のチェックを外す。これをオフにしておかないと、Windows Updateを手動化していてもDocker Desktop単体で更新・再起動を促してくることがあります。

---

## 2. リポジトリの取得

PowerShellで作業したいフォルダに移動して:

```powershell
git clone https://github.com/iyusei-76/NNWS.git
cd NNWS
```

---

## 3. .env を作成する

`.env`はgit管理外（`.gitignore`済み）なので、リポジトリには含まれていません。`NNWS`直下に新規作成し、以下を設定してください。

```env
# Slack
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx
SLACK_APP_TOKEN=xapp-xxxxxxxxxxxx

# PostgreSQL
POSTGRES_DB=slackbot
POSTGRES_USER=postgres
POSTGRES_PASSWORD=好きなパスワード

# Google OAuth
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxxxxx
GOOGLE_REDIRECT_URI=http://localhost:8080/oauth2callback   # ← 5章のtunnel作成後に書き換える
GOOGLE_TOKEN_ENCRYPTION_KEY=xxxxxxxx                          # 既存環境と同じ値を使うこと（変えると既存トークンが復号不能になる）
```

`GOOGLE_TOKEN_ENCRYPTION_KEY`が手元にない・新規に始める場合は、以下で生成:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> 既存の稼働環境からデータ（メッセージログ・連携済みGoogleトークン）を引き継ぎたい場合は、`.env`だけでなく`db/data`フォルダ（PostgreSQLの実データ）も丸ごとコピーしてきてください。持ってこない場合はまっさらなDBから始まります。

---

## 4. 一旦ローカルで起動確認

```powershell
docker compose up --build -d
docker compose logs bot --tail 50
```

起動ログに以下が出ればOKです。

```
✅ DB接続: OK
✅ Slack接続: OK (bot: ..., team: ...)
✅ Google OAuth設定: OK
```

> 初回構築（`db/data`が空の状態）であれば`db/init.sql`が自動実行されテーブルが作られます。既存の`db/data`を引き継いだ場合は、`google_credentials`テーブルがまだ無ければ以下を1回実行してください。
>
> ```powershell
> Get-Content db/migrations/001_add_google_credentials.sql | docker compose exec -T db psql -U postgres -d slackbot
> ```
>
> 同様に、`user_profiles`テーブル（入社年度・新卒/中途の登録用）がまだ無ければ以下も1回実行してください。
>
> ```powershell
> Get-Content db/migrations/002_add_user_profiles.sql | docker compose exec -T db psql -U postgres -d slackbot
> ```

---

## 5. Cloudflare Tunnelで外部公開する

他のメンバーがGoogle認証（`?google_auth`）を完了するには、あなたのデスクトップのポート8080に、`localhost`ではなく外部から届く固定アドレスが必要です（Google認証後のリダイレクトは各メンバー自身のブラウザから発生するため、`localhost`のままだとそのメンバー自身のPCを指してしまい繋がりません）。Cloudflare Tunnelで公開URLを発行して解決します。

### 5-1. cloudflaredのインストール（Windows）

wingetが使える場合:

```powershell
winget install --id Cloudflare.cloudflared
```

または https://github.com/cloudflare/cloudflared/releases から `cloudflared-windows-amd64.exe` をダウンロードし、`cloudflared.exe` にリネームして任意のフォルダに置く（PATHを通しておくと以降のコマンドが楽）。

確認:

```powershell
cloudflared --version
```

### 5-2. Quick Tunnelを起動する

アカウント登録不要の「クイックトンネル」で、`localhost:8080`を一時的に公開します。

```powershell
cloudflared tunnel --url http://localhost:8080
```

実行すると、ターミナルに以下のような公開URLが表示されます（起動するたびに変わります）。

```
https://random-words-1234.trycloudflare.com
```

このウィンドウは**開いたままにしておく**必要があります（閉じるとtunnelが切れます）。

> 常設運用でURLを固定したい場合は、Cloudflareアカウント＋独自ドメインを使った「名前付きTunnel」を後日検討してください（今回はデモ用途なのでQuick Tunnelで十分です）。

### 5-3. Googleと.envの設定を更新する

1. 表示された公開URLを控える（例: `https://random-words-1234.trycloudflare.com`）
2. `.env`の`GOOGLE_REDIRECT_URI`を書き換える。
   ```env
   GOOGLE_REDIRECT_URI=https://random-words-1234.trycloudflare.com/oauth2callback
   ```
3. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → 対象のOAuth 2.0クライアントID → 「承認済みのリダイレクトURI」に同じURLを追加して保存
4. Botを再起動して新しい設定を反映する。
   ```powershell
   docker compose up --build -d
   ```

---

## 6. 動作確認

SlackのDMで以下を試してください。

- `?ping`
- `?data`
- `?google_auth` → ボタンから連携 → 完了通知DMが届くか確認 → 続けて表示される「登録する」ボタンからモーダルを開き、入社年度・新卒/中途を選んで送信 → 登録完了DMが届くか確認 → 同じDMに表示される「1on1を作成する」ボタン→「新卒」「中途」「既存社員」「指定しない」から1つ選ぶ→条件に合う候補が最大3名ランダムに提示されるか確認
  - 候補者ボタン → 1on1予定が（ダミーで）仮登録されるか確認
  - 「もう一度選ぶ」ボタン → 同じカテゴリで再抽選されるか確認
  - 「自分で設定する」ボタン → @メンションの入力を促されるか、メンション送信後に仮登録されるか確認
- `?check`
- `?set 定例会議 07/22 14:00 60 @tanaka` → 予定が登録されMeetリンクが返るか確認（`@`はSlackの候補から選択して確定させること）

`?set`でユーザーを招待する場合、Slackアプリのボットトークンに`users:read` / `users:read.email`スコープが必要です。未設定だとメールアドレスが取得できず、その人は招待からスキップされます。

---

## 7. 注意事項

- **`cloudflared tunnel --url ...`のQuick Tunnelは、起動するたびに公開URLが変わります。** デスクトップの再起動・cloudflaredの再起動があった場合は、そのたびに以下3点セットを必ずやり直してください。片方だけ更新すると`redirect_uri_mismatch`エラーになります。
  1. `.env`の`GOOGLE_REDIRECT_URI`を新しいURLに書き換える
  2. Google Cloud Consoleの「承認済みのリダイレクトURI」にも同じ新しいURLを追加（古いURLは残っていても害はない）
  3. `docker compose up --build -d`でBotを再起動する（`.env`の変更はコンテナ再起動しないと反映されない）
- `.env`と`db/data`は絶対にgitにコミットしないでください（`.gitignore`済みですが、`git add -A`等で誤って追加しないよう注意）。
- `GOOGLE_TOKEN_ENCRYPTION_KEY`を変更すると、既存ユーザーが保存済みのGoogleトークンが復号できなくなり、全員`?google_auth`のやり直しが必要になります。
