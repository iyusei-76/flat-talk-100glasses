import os
import logging
import threading

from slack_bolt.adapter.socket_mode import SocketModeHandler

from auth import oauth_callback_server
from health_checks import run_all_checks
from slack.bolt_app import app
from slack import commands, profile_registration, one_on_one  # noqa: F401 (importすることでハンドラを登録)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


if __name__ == "__main__":
    # 起動時にDB / Slack / Googleの疎通・設定を確認
    run_all_checks(app)

    # Google OAuthのリダイレクトを受けるHTTPサーバーを別スレッドで起動
    oauth_thread = threading.Thread(target=oauth_callback_server.run_server, daemon=True)
    oauth_thread.start()

    app_token = os.environ.get("SLACK_APP_TOKEN")
    handler = SocketModeHandler(app, app_token)
    logger.info("Botを起動しました。コマンド受付開始...")
    handler.start()
