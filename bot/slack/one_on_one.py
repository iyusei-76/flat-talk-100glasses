import logging
import random
import re
from datetime import datetime

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


def _resolve_email(client, user_id):
    try:
        resp = client.users_info(user=user_id)
        return resp.get("user", {}).get("profile", {}).get("email")
    except Exception as e:
        logger.error(f"Slackメールアドレス取得エラー ({user_id}): {e}")
        return None


def _describe_user(slack_user_id, requester_id, partner_id):
    if slack_user_id == requester_id:
        return "あなた"
    if slack_user_id == partner_id:
        return f"相手（<@{partner_id}>）"
    return "対象者"


def _post_slot_candidates(post, requester_id, partner_id):
    """post: post(text=..., blocks=...)のシグネチャで呼べる送信関数
    （client.chat_postMessageの部分適用、またはBoltのsay）。"""
    try:
        candidates = calendar_client.find_1on1_slot_candidates(requester_id, partner_id)
    except calendar_client.NotAuthenticatedError as e:
        who = _describe_user(e.slack_user_id, requester_id, partner_id)
        post(
            text=(
                f"⚠️ {who}のGoogleカレンダーが連携されていないため、日程を調整できませんでした。\n"
                "`?google_auth` で連携してから再度お試しください。"
            )
        )
        return
    except scheduler.CalendarFetchError as e:
        who = _describe_user(e.slack_user_id, requester_id, partner_id)
        logger.error(f"1on1カレンダー取得エラー ({e.slack_user_id}): {e.cause}")
        post(text=f"⚠️ {who}のカレンダー取得に失敗しました。\n詳細: {e.cause}")
        return
    except scheduler.NoAvailableSlotError as e:
        post(text=f"⚠️ {e}")
        return
    except Exception as e:
        logger.error(f"1on1日程調整エラー ({requester_id} / {partner_id}): {e}")
        post(text=f"⚠️ 日程調整に失敗しました。\n詳細: {e}")
        return

    post(
        text=f"<@{partner_id}> との1on1候補日時を{len(candidates)}件選びました。",
        blocks=messages.one_on_one_slot_candidates_blocks(partner_id, candidates),
    )


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


# 候補者ボタン押下時、その相手との1on1候補日時を3件提示する
# （ボタンごとにaction_idを一意にする必要があるため "select_1on1_partner-<user_id>" にマッチさせる）
@app.action(re.compile(r"^select_1on1_partner-"))
def handle_select_1on1_partner(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    partner_id = body["actions"][0]["value"]
    _post_slot_candidates(
        lambda **kwargs: client.chat_postMessage(channel=user_id, **kwargs), user_id, partner_id
    )


# 候補日時ボタン押下時、その日時で1on1予定をGoogleカレンダーに実登録する
# （ボタンごとにaction_idを一意にする必要があるため "select_1on1_slot-<index>" にマッチさせる）
@app.action(re.compile(r"^select_1on1_slot-"))
def handle_select_1on1_slot(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    partner_id, start_iso, end_iso = body["actions"][0]["value"].split("|")
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    duration_minutes = int((end - start).total_seconds() // 60)

    try:
        still_available = calendar_client.is_1on1_slot_still_available(user_id, partner_id, start, end)
    except calendar_client.NotAuthenticatedError as e:
        who = _describe_user(e.slack_user_id, user_id, partner_id)
        client.chat_postMessage(
            channel=user_id,
            text=(
                f"⚠️ {who}のGoogleカレンダーが連携されていないため、登録できませんでした。\n"
                "`?google_auth` で連携してから再度お試しください。"
            ),
        )
        return
    except scheduler.CalendarFetchError as e:
        who = _describe_user(e.slack_user_id, user_id, partner_id)
        logger.error(f"1on1空き状況再チェックエラー ({e.slack_user_id}): {e.cause}")
        client.chat_postMessage(
            channel=user_id, text=f"⚠️ {who}のカレンダー確認に失敗しました。\n詳細: {e.cause}"
        )
        return
    except Exception as e:
        logger.error(f"1on1空き状況再チェックエラー ({user_id} / {partner_id}): {e}")
        client.chat_postMessage(channel=user_id, text=f"⚠️ 空き状況の確認に失敗しました。\n詳細: {e}")
        return

    if not still_available:
        client.chat_postMessage(
            channel=user_id,
            text="⚠️ この日時は既に埋まってしまったため登録できませんでした。もう一度候補を選び直してください。",
        )
        return

    requester_name = _resolve_display_name(client, user_id)
    partner_name = _resolve_display_name(client, partner_id)
    partner_email = _resolve_email(client, partner_id)
    title = f"1on1: {requester_name} ⇔ {partner_name}"

    try:
        event = calendar_client.create_event(
            user_id,
            title,
            start,
            duration_minutes,
            attendee_emails=[partner_email] if partner_email else None,
        )
    except calendar_client.NotAuthenticatedError:
        client.chat_postMessage(
            channel=user_id,
            text="⚠️ Googleカレンダーと連携されていません。`?google_auth` で連携してください。",
        )
        return
    except Exception as e:
        logger.error(f"1on1カレンダー登録エラー ({user_id} / {partner_id}): {e}")
        client.chat_postMessage(
            channel=user_id,
            text=f"⚠️ カレンダーへの登録に失敗しました。\n詳細: {e}",
        )
        return

    client.chat_postMessage(
        channel=user_id,
        text=messages.one_on_one_scheduled_text(partner_id, start, end, event, partner_email),
    )

    try:
        client.chat_postMessage(
            channel=partner_id,
            text=messages.one_on_one_confirmed_partner_text(user_id, start, end, event),
        )
    except Exception as e:
        logger.error(f"1on1確定DM送信エラー (partner: {partner_id}): {e}")


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
    _post_slot_candidates(say, user_id, partner_id)
    return True
