import logging

from profiles import profile_store

from . import messages
from .bolt_app import app

logger = logging.getLogger(__name__)


# 「登録する」ボタン押下時にプロフィール登録モーダルを開く
@app.action("open_profile_registration")
def handle_open_profile_registration(ack, body, client):
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=messages.profile_registration_view())


# プロフィール登録モーダル送信時にDBへ保存し、DMで確認メッセージを返す
@app.view("profile_registration_modal")
def handle_profile_registration_submission(ack, body, client, view):
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    join_year = int(values["join_year_block"]["join_year_select"]["selected_option"]["value"])
    hire_type = values["hire_type_block"]["hire_type_radio"]["selected_option"]["value"]

    try:
        profile_store.save_user_profile(user_id, join_year, hire_type)
    except Exception as e:
        logger.error(f"プロフィール保存エラー: {e}")
        client.chat_postMessage(
            channel=user_id,
            text=f"⚠️ プロフィールの登録に失敗しました。\n詳細: {e}",
        )
        return

    client.chat_postMessage(
        channel=user_id,
        text=f"✅ プロフィールを登録しました。\n入社年度: {join_year}年度 / {messages.hire_type_label(hire_type)}",
        blocks=messages.profile_registration_confirmation_blocks(join_year, hire_type),
    )

    from . import commands  # 循環importを避けるため遅延import

    commands.publish_home_view(client, user_id)
