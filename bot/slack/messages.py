"""Slack向けの文言・Block Kitテンプレートを集約するモジュール。

業務ロジック（DB検索・Google連携・カレンダー操作など）は含めず、
「Slackにどう見せるか」だけをここに置く。
"""

from datetime import datetime

STATIC_COMMANDS = {
    "ping": "pong! サクセスフル！！！",
    "spanking": "oh yes!!",
    "stupid": "as!",
}

HIRE_TYPE_OPTIONS = [
    ("新卒入社", "new_grad"),
    ("中途入社", "mid_career"),
]

CATEGORY_OPTIONS = [
    ("新卒", "new_grad"),
    ("中途", "mid_career"),
    ("既存社員", "existing"),
    ("指定しない", "any"),
]


def hire_type_label(value):
    return dict((v, k) for k, v in HIRE_TYPE_OPTIONS)[value]


def category_label(value):
    return dict((v, k) for k, v in CATEGORY_OPTIONS)[value]


# --- ?google_auth ---

def google_auth_prompt_blocks(auth_url):
    return [
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
    ]


# --- Google認証完了通知（OAuthコールバックサーバーから送信） ---

def google_auth_success_blocks():
    text = "✅ Googleアカウントとの連携が完了しました！\n続けて、入社年度などのプロフィールを登録してください。"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "登録する"},
                    "action_id": "open_profile_registration",
                    "style": "primary",
                }
            ],
        },
    ]


# --- プロフィール登録モーダル ---

def _join_year_options():
    current_year = datetime.now().year
    years = range(current_year + 1, current_year - 40, -1)
    return [
        {"text": {"type": "plain_text", "text": f"{year}年度"}, "value": str(year)}
        for year in years
    ]


def profile_registration_view():
    return {
        "type": "modal",
        "callback_id": "profile_registration_modal",
        "title": {"type": "plain_text", "text": "プロフィール登録"},
        "submit": {"type": "plain_text", "text": "登録"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "input",
                "block_id": "join_year_block",
                "label": {"type": "plain_text", "text": "入社年度"},
                "element": {
                    "type": "static_select",
                    "action_id": "join_year_select",
                    "placeholder": {"type": "plain_text", "text": "年度を選択"},
                    "options": _join_year_options(),
                },
            },
            {
                "type": "input",
                "block_id": "hire_type_block",
                "label": {"type": "plain_text", "text": "区分"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "hire_type_radio",
                    "options": [
                        {"text": {"type": "plain_text", "text": label}, "value": value}
                        for label, value in HIRE_TYPE_OPTIONS
                    ],
                },
            },
        ],
    }


def profile_registration_confirmation_blocks(join_year, hire_type_value):
    text = f"✅ プロフィールを登録しました。\n入社年度: {join_year}年度 / {hire_type_label(hire_type_value)}"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "1on1を作成する"},
                    "action_id": "open_1on1_category_selection",
                    "style": "primary",
                }
            ],
        },
    ]


# --- 1on1相手の抽選 ---

def one_on_one_category_selection_blocks():
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "1on1相手を探すカテゴリを選んでください。"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": label},
                    "action_id": f"select_1on1_category-{value}",
                    "value": value,
                }
                for label, value in CATEGORY_OPTIONS
            ],
        },
    ]


def one_on_one_no_candidates_blocks(category_label_text):
    text = f"「{category_label_text}」に該当する候補がいませんでした。"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "自分で設定する"},
                    "action_id": "manual_1on1_partner",
                }
            ],
        },
    ]


def one_on_one_candidates_blocks(category_value, category_label_text, candidates):
    """candidates: [(slack_user_id, display_name), ...]"""
    candidate_buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": display_name},
            "action_id": f"select_1on1_partner-{uid}",
            "value": uid,
        }
        for uid, display_name in candidates
    ]
    mention_lines = "\n".join(f"• <@{uid}>" for uid, _ in candidates)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*「{category_label_text}」の1on1候補*\n{mention_lines}",
            },
        },
        {"type": "actions", "elements": candidate_buttons},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "もう一度選ぶ"},
                    "action_id": "retry_1on1_category",
                    "value": category_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "自分で設定する"},
                    "action_id": "manual_1on1_partner",
                },
            ],
        },
    ]


def one_on_one_slot_candidates_blocks(partner_id, candidates):
    """candidates: [{"start": datetime, "end": datetime}, ...]（スコア降順）"""
    slot_buttons = [
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": f"{c['start'].strftime('%m/%d(%a) %H:%M')}〜{c['end'].strftime('%H:%M')}",
            },
            "action_id": f"select_1on1_slot-{i}",
            "value": f"{partner_id}|{c['start'].isoformat()}|{c['end'].isoformat()}",
        }
        for i, c in enumerate(candidates)
    ]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<@{partner_id}> との1on1候補日時です。都合の良いものを選んでください。",
            },
        },
        {"type": "actions", "elements": slot_buttons},
    ]


def one_on_one_scheduled_text(partner_id, start, end, event=None, partner_email=None):
    lines = [
        "✅ 1on1の予定をカレンダーに登録しました。",
        f"相手: <@{partner_id}>",
        f"日時: {start.strftime('%m/%d(%a) %H:%M')} 〜 {end.strftime('%H:%M')}",
    ]
    if event and event.get("hangoutLink"):
        lines.append(f"Meet: {event['hangoutLink']}")
    if not partner_email:
        lines.append(f"⚠️ <@{partner_id}>のメールアドレスが取得できず、招待できませんでした。")
    return "\n".join(lines)


def one_on_one_confirmed_partner_text(requester_id, start, end, event=None):
    lines = [
        f"📅 <@{requester_id}> さんとの1on1が確定しました。",
        f"日時: {start.strftime('%m/%d(%a) %H:%M')} 〜 {end.strftime('%H:%M')}",
    ]
    if event and event.get("hangoutLink"):
        lines.append(f"Meet: {event['hangoutLink']}")
    return "\n".join(lines)


MANUAL_PARTNER_PROMPT_TEXT = "1on1の相手を @ でメンションして送信してください。"
