"""Slack向けの文言・Block Kitテンプレートを集約するモジュール。

業務ロジック（DB検索・Google連携・カレンダー操作など）は含めず、
「Slackにどう見せるか」だけをここに置く。
"""

from datetime import datetime

STATIC_COMMANDS = {
    "ping": "pong! サクセスフル！！！",
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

HELP_TEXT = (
    "*【ふらっとトーク Botの使い方】*\n"
    "このBotとのDMで以下のコマンドを送信してください。\n\n"
    "• `?help` : このヘルプを表示\n"
    "• `?start` : 認証・プロフィール登録・1on1作成のうち、途中までしか終わっていないところから続きを案内\n"
    "• `?ping` : 疎通確認\n"
    "• `?google_auth` : Googleカレンダーとの連携\n"
    "• `?check` : 本日〜明日の予定を確認\n"
    "• `?set タイトル MM/DD HH:MM 所要分 [@招待したい人...]` : 予定をカレンダーに登録\n"
    "　例: `?set 定例会議 07/22 14:00 60 @tanaka @suzuki`\n"
    "• `?survey` : 実施済みの1on1について日程アンケートに回答\n"
    "• `?invite_pause` : 1on1候補としての招待を一時停止\n"
    "• `?invite_resume` : 1on1候補としての招待を再開\n\n"
    "*【1on1について】*\n"
    "Googleカレンダー連携・プロフィール登録が完了すると、コマンド以外の文字列を送った際に「1on1を作成する」ボタンが表示されます。"
    "そこから相手を選ぶか自分で指定し、提示された候補日時、または「自分で設定する」から日時を指定して1on1を予約できます。"
)


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


def set_command_1on1_suggestion_blocks(text, partner_id):
    """?setの応答に「1on1を設定する」ボタンを添える（@メンションが含まれていた場合）。
    ボタンのaction_idはone_on_one.handle_select_1on1_partnerと共通（相手ユーザーIDで即候補提示させる）。"""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "1on1を設定する"},
                    "action_id": f"select_1on1_partner-{partner_id}",
                    "value": partner_id,
                }
            ],
        },
    ]


def one_on_one_entry_blocks():
    text = "プロフィール登録済みです。1on1の相手を探しましょう。"
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
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "自分で設定する"},
                    "action_id": "manual_1on1_slot",
                    "value": partner_id,
                }
            ],
        },
    ]


def one_on_one_scheduled_text(partner_id, partner_email=None, partner_notified=True):
    lines = ["✅ 1on1の予定を登録しました。"]
    if not partner_email:
        lines.append(f"⚠️ <@{partner_id}>のメールアドレスが取得できず、招待できませんでした。")
    if partner_notified:
        lines.append(f"<@{partner_id}>に予定確定のDMを送信しました。")
    else:
        lines.append(f"⚠️ <@{partner_id}>への予定確定DMの送信に失敗しました。")
    return "\n".join(lines)


def one_on_one_confirmed_partner_text(requester_id, start, end, event=None, invited_to_calendar=False):
    lines = [
        f"📅 <@{requester_id}> さんとの1on1が確定しました。",
        f"日時: {start.strftime('%m/%d(%a) %H:%M')} 〜 {end.strftime('%H:%M')}",
    ]
    if event and event.get("hangoutLink"):
        lines.append(f"Meet: {event['hangoutLink']}")
    if invited_to_calendar:
        lines.append("都合が悪い場合は、カレンダーの招待から「辞退」を選択していただくだけで大丈夫です。")
    return "\n".join(lines)


MANUAL_PARTNER_PROMPT_TEXT = "1on1の相手を @ でメンションして送信してください。"


# --- 1on1招待の受付停止/再開（?invite_pause / ?invite_resume） ---

INVITE_PAUSED_TEXT = "🔕 1on1の招待を一時停止しました。カテゴリ抽選の候補から外れます。`?invite_resume` で再開できます。"
INVITE_RESUMED_TEXT = "🔔 1on1の招待を再開しました。"
INVITE_TOGGLE_REQUIRES_PROFILE_TEXT = "⚠️ プロフィール登録が完了していないため設定できません。`?start` から登録してください。"


# --- 実施後アンケート（?survey） ---

NO_PENDING_SURVEYS_TEXT = "アンケート回答待ちの1on1はありません。"
SURVEY_THANKS_TEXT = "✅ アンケートへの回答ありがとうございました。"

_SCHEDULE_SCORE_LABELS = {
    0: "0: 忙しくて迷惑だった",
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5: ちょうどよかった",
}


def one_on_one_survey_prompt_blocks(event_id, other_user_id, start, end, remaining_count=0):
    lines = [
        "*アンケート*\n日程のレコメンドはいかがでしたか？",
        f"<@{other_user_id}> との1on1（{start.strftime('%m/%d(%a) %H:%M')}〜{end.strftime('%H:%M')}）",
    ]
    if remaining_count > 0:
        lines.append(f"（ほかに回答待ちが{remaining_count}件あります。回答後にもう一度 `?survey` を送ってください）")

    score_buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": f"survey_score-{event_id}-{score}",
            "value": f"{event_id}|{score}",
        }
        for score, label in _SCHEDULE_SCORE_LABELS.items()
    ]

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {"type": "actions", "elements": score_buttons},
    ]


def manual_1on1_slot_view(partner_id):
    return {
        "type": "modal",
        "callback_id": "manual_1on1_slot_modal",
        "private_metadata": partner_id,
        "title": {"type": "plain_text", "text": "日時を指定"},
        "submit": {"type": "plain_text", "text": "予約する"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "input",
                "block_id": "manual_slot_date_block",
                "label": {"type": "plain_text", "text": "日付"},
                "element": {
                    "type": "datepicker",
                    "action_id": "manual_slot_date_select",
                    "placeholder": {"type": "plain_text", "text": "日付を選択"},
                },
            },
            {
                "type": "input",
                "block_id": "manual_slot_time_block",
                "label": {"type": "plain_text", "text": "時刻"},
                "element": {
                    "type": "timepicker",
                    "action_id": "manual_slot_time_select",
                    "placeholder": {"type": "plain_text", "text": "時刻を選択"},
                },
            },
        ],
    }
