import logging
from datetime import datetime, time as dtime, timedelta

import jpholiday
from googleapiclient.discovery import build

from auth import google_oauth

from .calendar_client import JST, NotAuthenticatedError

logger = logging.getLogger(__name__)

SLOT_MINUTES = 30
DAY_START_TIME = dtime(9, 30)
DAY_END_TIME = dtime(18, 30)
LUNCH_START_TIME = dtime(12, 0)
LUNCH_END_TIME = dtime(13, 0)

# 明日以降、土日祝を除いて何営業日分を候補にするか
CANDIDATE_BUSINESS_DAYS = 8

# 前後の予定に挟まれている枠への減点
ADJACENT_BUSY_PENALTY = 2
# 3時間（180分）以上の連続busyブロックになってしまう枠への減点
MAX_CONTINUOUS_MINUTES = 180
LONG_BLOCK_BASE_PENALTY = 8
LONG_BLOCK_EXTRA_PENALTY_PER_SLOT = 2
# 昼休憩(12:00〜13:00)にかぶる30分枠1つあたりの減点
LUNCH_OVERLAP_PENALTY_PER_SLOT = 1
# 日付が近いほど加点する単位（候補日リストの先頭からの営業日数×この値）
PROXIMITY_BONUS_PER_DAY = 1.0


class NoAvailableSlotError(Exception):
    pass


class CalendarFetchError(Exception):
    """認証済みだがGoogle Calendar APIの呼び出し自体に失敗した場合に送出する。"""

    def __init__(self, slack_user_id, cause):
        super().__init__(f"{slack_user_id}: {cause}")
        self.slack_user_id = slack_user_id
        self.cause = cause


def _candidate_business_days(base_date, num_days=CANDIDATE_BUSINESS_DAYS):
    days = []
    offset = 1
    while len(days) < num_days:
        d = base_date + timedelta(days=offset)
        if d.weekday() < 5 and not jpholiday.is_holiday(d):  # 土(5)・日(6)・祝日を除く
            days.append(d)
        offset += 1
    return days


def _day_slots(date):
    start_dt = datetime.combine(date, DAY_START_TIME, tzinfo=JST)
    end_dt = datetime.combine(date, DAY_END_TIME, tzinfo=JST)
    slots = []
    cur = start_dt
    while cur + timedelta(minutes=SLOT_MINUTES) <= end_dt:
        slots.append((cur, cur + timedelta(minutes=SLOT_MINUTES)))
        cur += timedelta(minutes=SLOT_MINUTES)
    return slots


def _lunch_slot_indices(slots):
    indices = set()
    for i, (slot_start, slot_end) in enumerate(slots):
        lunch_start = slot_start.replace(
            hour=LUNCH_START_TIME.hour, minute=LUNCH_START_TIME.minute, second=0, microsecond=0
        )
        lunch_end = slot_start.replace(
            hour=LUNCH_END_TIME.hour, minute=LUNCH_END_TIME.minute, second=0, microsecond=0
        )
        if slot_start < lunch_end and slot_end > lunch_start:
            indices.add(i)
    return indices


def _fetch_busy_intervals(slack_user_id, time_min, time_max):
    credentials = google_oauth.load_credentials(slack_user_id)
    if not credentials:
        raise NotAuthenticatedError(slack_user_id)

    try:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        response = (
            service.freebusy()
            .query(
                body={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "items": [{"id": "primary"}],
                }
            )
            .execute()
        )
    except Exception as e:
        raise CalendarFetchError(slack_user_id, e) from e

    busy_periods = response["calendars"]["primary"].get("busy", [])
    return [
        (
            datetime.fromisoformat(period["start"]).astimezone(JST),
            datetime.fromisoformat(period["end"]).astimezone(JST),
        )
        for period in busy_periods
    ]


def _slot_is_busy(slot, busy_intervals):
    slot_start, slot_end = slot
    return any(slot_start < b_end and slot_end > b_start for b_start, b_end in busy_intervals)


def _busy_flags_by_day(slack_user_id, days, time_min, time_max):
    busy_intervals = _fetch_busy_intervals(slack_user_id, time_min, time_max)
    return {
        date: [_slot_is_busy(slot, busy_intervals) for slot in _day_slots(date)]
        for date in days
    }


def is_slot_still_available(requester_id, partner_id, start, end):
    """候補提示からユーザーが選ぶまでの間に埋まっていないか、確定直前に再チェックする。"""
    slot = (start, end)
    requester_busy = _fetch_busy_intervals(requester_id, start, end)
    if _slot_is_busy(slot, requester_busy):
        return False

    partner_busy = _fetch_busy_intervals(partner_id, start, end)
    return not _slot_is_busy(slot, partner_busy)


def _contiguous_busy_minutes(busy_flags, occupied_start, occupied_end):
    """occupied_start:occupied_end（新規予定分）を仮にbusyとして重ねた場合の、
    前後に連続するbusyブロックの合計分数を返す。"""
    n = len(busy_flags)
    combined = list(busy_flags)
    for i in range(occupied_start, occupied_end):
        combined[i] = True

    left = occupied_start
    while left - 1 >= 0 and combined[left - 1]:
        left -= 1

    right = occupied_end
    while right < n and combined[right]:
        right += 1

    return (right - left) * SLOT_MINUTES


def _score_candidate(
    requester_busy, partner_busy, lunch_indices, start_idx, end_idx, n_slots, days_from_now
):
    # 候補日リストの先頭（=最も近い営業日）を0として、遠い日ほど加点が減っていく
    score = PROXIMITY_BONUS_PER_DAY * -days_from_now

    if start_idx - 1 >= 0 and (requester_busy[start_idx - 1] or partner_busy[start_idx - 1]):
        score -= ADJACENT_BUSY_PENALTY
    if end_idx < n_slots and (requester_busy[end_idx] or partner_busy[end_idx]):
        score -= ADJACENT_BUSY_PENALTY

    for busy_flags in (requester_busy, partner_busy):
        block_minutes = _contiguous_busy_minutes(busy_flags, start_idx, end_idx)
        if block_minutes >= MAX_CONTINUOUS_MINUTES:
            extra_slots = (block_minutes - MAX_CONTINUOUS_MINUTES) // SLOT_MINUTES
            score -= LONG_BLOCK_BASE_PENALTY + LONG_BLOCK_EXTRA_PENALTY_PER_SLOT * extra_slots

    lunch_overlap_slots = len(set(range(start_idx, end_idx)) & lunch_indices)
    score -= LUNCH_OVERLAP_PENALTY_PER_SLOT * lunch_overlap_slots

    return score


def _generate_candidates(days, requester_busy_by_day, partner_busy_by_day, duration_minutes):
    duration_slots = duration_minutes // SLOT_MINUTES
    candidates = []

    for days_from_now, date in enumerate(days):
        slots = _day_slots(date)
        n_slots = len(slots)
        lunch_indices = _lunch_slot_indices(slots)
        requester_busy = requester_busy_by_day[date]
        partner_busy = partner_busy_by_day[date]

        for start_idx in range(0, n_slots - duration_slots + 1):
            end_idx = start_idx + duration_slots
            if any(requester_busy[start_idx:end_idx]) or any(partner_busy[start_idx:end_idx]):
                continue

            score = _score_candidate(
                requester_busy, partner_busy, lunch_indices, start_idx, end_idx, n_slots, days_from_now
            )
            candidates.append(
                {
                    "date": date,
                    "start": slots[start_idx][0],
                    "end": slots[end_idx - 1][1],
                    "score": score,
                }
            )

    return candidates


def _sorted_candidates(requester_id, partner_id, duration_minutes):
    if duration_minutes <= 0 or duration_minutes % SLOT_MINUTES != 0:
        raise ValueError(f"duration_minutes must be a positive multiple of {SLOT_MINUTES}")

    today = datetime.now(JST).date()
    days = _candidate_business_days(today)
    if not days:
        raise NoAvailableSlotError("候補となる営業日が見つかりませんでした。")

    time_min = datetime.combine(days[0], DAY_START_TIME, tzinfo=JST)
    time_max = datetime.combine(days[-1], DAY_END_TIME, tzinfo=JST)

    requester_busy_by_day = _busy_flags_by_day(requester_id, days, time_min, time_max)
    partner_busy_by_day = _busy_flags_by_day(partner_id, days, time_min, time_max)

    candidates = _generate_candidates(days, requester_busy_by_day, partner_busy_by_day, duration_minutes)
    if not candidates:
        raise NoAvailableSlotError("双方の空き時間が見つかりませんでした。")

    # スコア降順、同点なら早い日時を優先
    candidates.sort(key=lambda c: (-c["score"], c["date"], c["start"]))
    return candidates


def find_top_slots(requester_id, partner_id, duration_minutes=30, top_n=3):
    """両者のGoogleカレンダーから空き時間を探し、スコアリングモデルに基づき
    上位top_n件の1on1候補枠を返す。同じ日の枠が並んでも選択肢として意味が薄いため、
    1日につき最もスコアの高い枠を1つだけ採用し、その中から上位top_n日分を返す。
    見つからない場合はNoAvailableSlotErrorを送出する。"""
    candidates = _sorted_candidates(requester_id, partner_id, duration_minutes)

    best_per_day = {}
    for c in candidates:  # スコア降順ソート済みなので、各日について最初に出てきたものが最良
        best_per_day.setdefault(c["date"], c)

    top = sorted(best_per_day.values(), key=lambda c: (-c["score"], c["date"], c["start"]))[:top_n]
    return [{"start": c["start"], "end": c["end"], "score": c["score"]} for c in top]
