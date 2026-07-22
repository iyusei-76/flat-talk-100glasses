import logging
import random
import re

from gcal import calendar_client, scheduler
from profiles import profile_store

from . import messages
from .bolt_app import app

logger = logging.getLogger(__name__)

# 1on1の相手を @ で指定してもらう「自分で設定する」フローの入力待ちユーザー（プロセス内メモリ）
_pending_manual_partners = set()


def _resolve_display_name(client, user_id):
    try:
        resp = client.users_info(user=user_id)
        profile = resp.get("user", {}).get("profile", {})
        return profile.get("display_name") or profile.get("real_name") or user_id
    except Exception as e:
        logger.error(f"Slackユーザー情報取得エラー ({user_id}): {e}")
        return user_id


def _describe_user(slack_user_id, requester_id, partner_id):
    if slack_user_id == requester_id:
        return "あなた"
    if slack_user_id == partner_id:
        return f"相手（<@{partner_id}>）"
    return "対象者"


def _scheduled_message_text(requester_id, partner_id):
    try:
        slot = calendar_client.find_best_1on1_slot(requester_id, partner_id)
    except calendar_client.NotAuthenticatedError as e:
        who = _describe_user(e.slack_user_id, requester_id, partner_id)
        return (
            f"⚠️ {who}のGoogleカレンダーが連携されていないため、日程を調整できませんでした。\n"
            "`?google_auth` で連携してから再度お試しください。"
        )
    except scheduler.CalendarFetchError as e:
        who = _describe_user(e.slack_user_id, requester_id, partner_id)
        logger.error(f"1on1カレンダー取得エラー ({e.slack_user_id}): {e.cause}")
        return f"⚠️ {who}のカレンダー取得に失敗しました。\n詳細: {e.cause}"
    except scheduler.NoAvailableSlotError as e:
        return f"⚠️ {e}"
    except Exception as e:
        logger.error(f"1on1日程調整エラー ({requester_id} / {partner_id}): {e}")
        return f"⚠️ 日程調整に失敗しました。\n詳細: {e}"

    return messages.one_on_one_scheduled_text(partner_id, slot["start"], slot["end"])


def _post_candidates(client, user_id, category):
    category_label = messages.category_label(category)

    try:
        candidate_ids = profile_store.get_candidate_slack_user_ids(
            category, profile_store.current_fiscal_year(), exclude_user_id=user_id
        )
    except Exception as e:
        logger.error(f"1on1候補取得エラー: {e}")
        client.chat_postMessage(
            channel=user_id,
            text=f"⚠️ 候補の取得に失敗しました。\n詳細: {e}",
        )
        return

    if not candidate_ids:
        client.chat_postMessage(
            channel=user_id,
            text=f"「{category_label}」に該当する候補がいませんでした。",
            blocks=messages.one_on_one_no_candidates_blocks(category_label),
        )
        return

    picked_ids = random.sample(candidate_ids, k=min(3, len(candidate_ids)))
    candidates = [(uid, _resolve_display_name(client, uid)) for uid in picked_ids]
    client.chat_postMessage(
        channel=user_id,
        text=f"「{category_label}」の1on1候補を{len(candidates)}名選びました。",
        blocks=messages.one_on_one_candidates_blocks(category, category_label, candidates),
    )


# 「1on1を作成する」ボタン押下時に、相手のカテゴリ選択ボタンを表示する
@app.action("open_1on1_category_selection")
def handle_open_1on1_category_selection(ack, body, client):
    ack()
    client.chat_postMessage(
        channel=body["user"]["id"],
        text="1on1相手を探すカテゴリを選んでください。",
        blocks=messages.one_on_one_category_selection_blocks(),
    )


# カテゴリ選択後、条件に合う候補をDBから探しランダムに3名提示する
# （ボタンごとにaction_idを一意にする必要があるため "select_1on1_category-<category>" にマッチさせる）
@app.action(re.compile(r"^select_1on1_category-"))
def handle_select_1on1_category(ack, body, client):
    ack()
    _post_candidates(client, body["user"]["id"], body["actions"][0]["value"])


# 「もう一度選ぶ」ボタン押下時、同じカテゴリで再抽選する
@app.action("retry_1on1_category")
def handle_retry_1on1_category(ack, body, client):
    ack()
    _post_candidates(client, body["user"]["id"], body["actions"][0]["value"])


# 候補者ボタン押下時、その相手との1on1予定を（ダミーで）登録する
# （ボタンごとにaction_idを一意にする必要があるため "select_1on1_partner-<user_id>" にマッチさせる）
@app.action(re.compile(r"^select_1on1_partner-"))
def handle_select_1on1_partner(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    partner_id = body["actions"][0]["value"]
    client.chat_postMessage(
        channel=user_id,
        text=_scheduled_message_text(user_id, partner_id),
    )


# 「自分で設定する」ボタン押下時、相手を @ で指定してもらう入力待ち状態にする
@app.action("manual_1on1_partner")
def handle_manual_1on1_partner(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    _pending_manual_partners.add(user_id)
    client.chat_postMessage(channel=user_id, text=messages.MANUAL_PARTNER_PROMPT_TEXT)


def try_handle_pending_manual_partner(user_id, text, say):
    """「自分で設定する」フローで@メンション入力待ちのユーザーからのDMを処理する。
    該当ユーザーでなければFalseを返し、通常のコマンドルーティングに委ねる。
    """
    if user_id not in _pending_manual_partners:
        return False

    mention_ids = calendar_client.extract_mention_ids(text)
    if not mention_ids:
        say("⚠️ @ でメンションして1名指定してください。")
        return True

    partner_id = mention_ids[0]
    if partner_id == user_id:
        say("⚠️ 自分自身は指定できません。別の相手を @ でメンションしてください。")
        return True

    _pending_manual_partners.discard(user_id)
    say(_scheduled_message_text(user_id, partner_id))
    return True
