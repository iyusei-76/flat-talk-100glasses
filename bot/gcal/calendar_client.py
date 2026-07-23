import re
import uuid
import logging
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from auth import google_oauth

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>")

_SET_USAGE = (
    "入力形式: `?set タイトル MM/DD HH:MM 所要分 [@招待したい人...]`\n"
    "例: `?set 定例会議 07/22 14:00 60 @tanaka @suzuki`"
)


class NotAuthenticatedError(Exception):
    def __init__(self, slack_user_id=None):
        super().__init__(slack_user_id)
        self.slack_user_id = slack_user_id


class InvalidEventInputError(Exception):
    pass


def _time_range_today_tomorrow():
    now = datetime.now(JST)
    tomorrow_end = (now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
    return now, tomorrow_end


def get_upcoming_events(slack_user_id):
    credentials = google_oauth.load_credentials(slack_user_id)
    if not credentials:
        raise NotAuthenticatedError()

    time_min, time_max = _time_range_today_tomorrow()

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    response = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return response.get("items", [])


def extract_mention_ids(text):
    return _MENTION_RE.findall(text)


def _resolve_start_dt(month, day, hour, minute):
    """月日時分から開始日時を組み立てる。現在時刻より過去になる場合は年をまたいだ指定とみなして翌年に繰り上げる。"""
    now = datetime.now(JST)
    try:
        start_dt = datetime(now.year, month, day, hour, minute, tzinfo=JST)
    except ValueError:
        raise InvalidEventInputError("日付または時刻の値が不正です。")

    if start_dt < now:
        try:
            start_dt = start_dt.replace(year=now.year + 1)
        except ValueError:
            raise InvalidEventInputError("日付または時刻の値が不正です。")

    return start_dt


def parse_set_command(args_text):
    mention_ids = _MENTION_RE.findall(args_text)
    plain_text = _MENTION_RE.sub(" ", args_text)

    unresolved_mentions = re.findall(r"@\S+", plain_text)
    if unresolved_mentions:
        raise InvalidEventInputError(
            "@メンションがSlackの候補選択で確定されていないようです。"
            "入力候補（オートコンプリート）が表示された状態で候補をクリック/Tabで選択してから送信してください。\n"
            f"（未確定のまま検出: {', '.join(unresolved_mentions)}）"
        )

    tokens = plain_text.split()
    if len(tokens) < 4:
        raise InvalidEventInputError(_SET_USAGE)

    date_str, time_str, duration_str = tokens[-3], tokens[-2], tokens[-1]
    title = " ".join(tokens[:-3]).strip()

    date_match = _DATE_RE.match(date_str)
    time_match = _TIME_RE.match(time_str)

    if not title or not date_match or not time_match or not duration_str.isdigit():
        raise InvalidEventInputError(_SET_USAGE)

    duration_minutes = int(duration_str)
    if duration_minutes <= 0:
        raise InvalidEventInputError("所要分は1以上の整数で指定してください。")

    month, day = int(date_match.group(1)), int(date_match.group(2))
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    start_dt = _resolve_start_dt(month, day, hour, minute)

    return title, start_dt, duration_minutes, mention_ids


def create_event(slack_user_id, title, start_dt, duration_minutes, attendee_emails=None):
    credentials = google_oauth.load_credentials(slack_user_id)
    if not credentials:
        raise NotAuthenticatedError()

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    body = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Tokyo"},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if attendee_emails:
        body["attendees"] = [{"email": email} for email in attendee_emails]

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    return (
        service.events()
        .insert(
            calendarId="primary",
            body=body,
            conferenceDataVersion=1,
            sendUpdates="all" if attendee_emails else "none",
        )
        .execute()
    )


def find_1on1_slot_candidates(requester_id, partner_id, duration_minutes=30, top_n=3):
    from . import scheduler  # 循環importを避けるため遅延import

    return scheduler.find_top_slots(requester_id, partner_id, duration_minutes, top_n)


def is_1on1_slot_still_available(requester_id, partner_id, start, end):
    from . import scheduler  # 循環importを避けるため遅延import

    return scheduler.is_slot_still_available(requester_id, partner_id, start, end)


def format_events_message(events):
    now = datetime.now(JST)
    header = f"*【本日 {now.strftime('%H:%M')} 以降〜明日の予定】*"

    if not events:
        return f"{header}\n予定はありません。"

    lines = [header]
    current_date = None
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        summary = event.get("summary", "(タイトルなし)")

        if "T" in start:
            dt = datetime.fromisoformat(start)
            date_str = dt.strftime("%m/%d(%a)")
            time_str = dt.strftime("%H:%M")
        else:
            date_str = datetime.fromisoformat(start).strftime("%m/%d(%a)")
            time_str = "終日"

        if date_str != current_date:
            lines.append(f"\n*{date_str}*")
            current_date = date_str
        lines.append(f"• {time_str} {summary}")

    return "\n".join(lines)
