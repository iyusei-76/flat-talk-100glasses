import os
import logging

from flask import Flask, request
from slack_sdk import WebClient

from . import google_oauth
from slack import messages

logger = logging.getLogger(__name__)

flask_app = Flask(__name__)
_slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))


@flask_app.route("/oauth2callback")
def oauth2callback():
    error = request.args.get("error")
    state = request.args.get("state")
    code = request.args.get("code")

    if error:
        logger.warning(f"Google OAuthエラー: {error}")
        return "認証がキャンセルされました。Slackに戻ってもう一度お試しください。", 400

    if not state or not code:
        return "不正なリクエストです。", 400

    state_entry = google_oauth.resolve_state(state)
    if not state_entry:
        return "認証セッションが無効か期限切れです。Slackでもう一度コマンドを実行してください。", 400

    slack_user_id = state_entry["slack_user_id"]

    try:
        credentials = google_oauth.exchange_code_for_credentials(code, state_entry["code_verifier"])
        google_oauth.save_credentials(slack_user_id, credentials)
    except Exception:
        logger.exception("Google OAuthのトークン交換に失敗しました")
        _notify_slack(slack_user_id, "⚠️ Google連携に失敗しました。もう一度お試しください。")
        return "認証処理でエラーが発生しました。", 500

    _notify_slack(
        slack_user_id,
        "✅ Googleアカウントとの連携が完了しました！",
        blocks=messages.google_auth_success_blocks(),
    )

    from slack import commands  # 循環importを避けるため遅延import

    commands.publish_home_view(_slack_client, slack_user_id)

    return "Googleアカウントとの連携が完了しました。このタブは閉じて構いません。"


def _notify_slack(slack_user_id, text, blocks=None):
    try:
        _slack_client.chat_postMessage(channel=slack_user_id, text=text, blocks=blocks)
    except Exception:
        logger.exception("Slackへの通知送信に失敗しました")


def run_server():
    port = int(os.environ.get("OAUTH_SERVER_PORT", "8080"))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False, debug=False)
