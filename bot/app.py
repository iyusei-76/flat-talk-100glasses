import os
import logging
import threading
import psycopg2
from datetime import datetime, timedelta
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import google_auth
import calendar_client
import oauth_server
from health_checks import run_all_checks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

'''envの変数
SLACK_BOT_TOKEN
SLACK_APP_TOKEN
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI
GOOGLE_TOKEN_ENCRYPTION_KEY
'''


# DB接続用の関数（message_logs用）
def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD")
    )

# ==========================================
# 1. シンプルな固定返答コマンドの定義
# 今後追加したい場合は、ここの辞書を増やすだけでOKです！
# ==========================================
STATIC_COMMANDS = {
    "ping": "pong! サクセスフル！！！",
    "spanking": "oh yes!!",
    "stupid": "as!"
}


# SlackユーザーIDのリストをメールアドレスに解決する（?set の招待先解決用）
def resolve_attendee_emails(mention_ids):
    emails = []
    failed_ids = []
    for uid in mention_ids:
        try:
            resp = app.client.users_info(user=uid)
            email = resp.get("user", {}).get("profile", {}).get("email")
        except Exception as e:
            logger.error(f"Slackユーザー情報取得エラー ({uid}): {e}")
            email = None

        if email:
            emails.append(email)
        else:
            failed_ids.append(uid)

    return emails, failed_ids

# すべてのメッセージイベントをキャッチするハンドラ
@app.event("message")
def handle_im_messages(body, say, logger):
    event = body.get("event", {})
    
    # DM以外、またはBot自身が送信したメッセージは無視する
    if event.get("channel_type") != "im" or "bot_id" in event:
        return

    user_id = event.get("user")
    text = event.get("text", "").strip()

    # --- A. まず全てのメッセージをDBに記録 ---
    db_error = None
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO message_logs (user_id, message) VALUES (%s, %s)",
                    (user_id, text)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"DB Insert Error: {e}")
        db_error = str(e)


    # --- B. コマンドのルーティング（振り分け） ---
    
    # 1. 固定返答コマンドの場合
    if text in STATIC_COMMANDS:
        say(STATIC_COMMANDS[text])

    # 2. 動的処理コマンド: /ping (受信時間 or エラー)
    elif text == "?ping":
        if db_error:
            say(f"⚠️ エラーコード: DB_SAVE_ERROR\n詳細: {db_error}")
        else:
            # 現在時刻を取得して返す
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            say(f"⏱️ レスポンス受信時刻: {now}")

    # 3. 動的処理コマンド: /data (DBの最新5件)
    elif text == "?data":
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # 最新から5件取得
                    cur.execute(
                        "SELECT id, user_id, message, created_at FROM message_logs ORDER BY created_at DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
            
            if rows:
                response_lines = ["*【データベース最新5件】*"]
                for row in rows:
                    # Slackの仕様に合わせてユーザーIDをメンション形式（<@ID>）にする
                    time_str = row[3].strftime("%m/%d %H:%M:%S")
                    response_lines.append(f"• `ID:{row[0]}` | User: <@{row[1]}> | Msg: {row[2]} | Time: {time_str}")
                say("\n".join(response_lines))
            else:
                say("データベースにはまだ何も記録されていません。")
        except Exception as e:
            logger.error(f"DB Select Error: {e}")
            say(f"⚠️ エラーコード: DB_READ_ERROR\n詳細: {e}")

    # 5. Google連携コマンド: ?google_auth
    elif text == "?google_auth":
        try:
            auth_url = google_auth.create_authorization_url(user_id)
        except Exception as e:
            logger.error(f"Google認証URL生成エラー: {e}")
            say("⚠️ Google連携の設定が未完了です。管理者に確認してください。")
        else:
            say(
                text="Googleカレンダーとの連携",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Googleカレンダーと連携するには、下のボタンから認証を行ってください。",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Googleと連携する"},
                                "url": auth_url,
                                "action_id": "google_oauth_connect",
                            }
                        ],
                    },
                ],
            )

    # 6. カレンダー確認コマンド: ?check（本日送信時以降〜明日の予定）
    elif text == "?check":
        try:
            events = calendar_client.get_upcoming_events(user_id)
        except calendar_client.NotAuthenticatedError:
            say("⚠️ Googleカレンダーと連携されていません。`?google_auth` で連携してください。")
        except Exception as e:
            logger.error(f"Calendar取得エラー: {e}")
            say(f"⚠️ 予定の取得に失敗しました。\n詳細: {e}")
        else:
            say(calendar_client.format_events_message(events))

    # 7. カレンダー登録コマンド: ?set タイトル MM/DD HH:MM 所要分 [@招待したい人...]
    elif text == "?set" or text.startswith("?set "):
        args_text = text[len("?set"):].strip()
        try:
            title, start_dt, duration_minutes, mention_ids = calendar_client.parse_set_command(args_text)
            attendee_emails, failed_mentions = resolve_attendee_emails(mention_ids)
            event = calendar_client.create_event(user_id, title, start_dt, duration_minutes, attendee_emails)
        except calendar_client.InvalidEventInputError as e:
            say(f"⚠️ {e}")
        except calendar_client.NotAuthenticatedError:
            say("⚠️ Googleカレンダーと連携されていません。`?google_auth` で連携してください。")
        except Exception as e:
            logger.error(f"Calendar登録エラー: {e}")
            say(f"⚠️ 予定の登録に失敗しました。\n詳細: {e}")
        else:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            lines = [
                "✅ 予定を登録しました。",
                f"*{title}*\n{start_dt.strftime('%m/%d(%a) %H:%M')} 〜 {end_dt.strftime('%H:%M')}",
            ]
            if event.get("hangoutLink"):
                lines.append(f"Meet: {event['hangoutLink']}")
            if attendee_emails:
                lines.append(f"招待: {', '.join(attendee_emails)}")
            if failed_mentions:
                mention_list = ", ".join(f"<@{uid}>" for uid in failed_mentions)
                lines.append(f"⚠️ メールアドレスが取得できず招待できなかったユーザー: {mention_list}")
            say("\n".join(lines))

    # 8. 定義されていない言葉の場合
    else:
        # 何もしない、またはエラーを返すなど（現在は無言の設定）
        pass


# Google連携ボタン（URLボタン）押下時のイベントをack応答のみで受け流す
@app.action("google_oauth_connect")
def handle_google_oauth_button(ack):
    ack()


if __name__ == "__main__":
    # 起動時にDB / Slack / Googleの疎通・設定を確認
    run_all_checks(app)

    # Google OAuthのリダイレクトを受けるHTTPサーバーを別スレッドで起動
    oauth_thread = threading.Thread(target=oauth_server.run_server, daemon=True)
    oauth_thread.start()

    app_token = os.environ.get("SLACK_APP_TOKEN")
    handler = SocketModeHandler(app, app_token)
    logger.info("Botを起動しました。コマンド受付開始...")
    handler.start()