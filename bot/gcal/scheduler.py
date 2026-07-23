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
# 昼休憩直後（食休みで動きたくない時間帯）
POST_LUNCH_START_TIME = dtime(13, 0)
POST_LUNCH_END_TIME = dtime(13, 30)

# 明日以降、土日祝を除いて何営業日分を候補にするか
CANDIDATE_BUSINESS_DAYS = 8

# スコアは最終的にこの範囲へクリップする（各項目の重みは大まかな目安でよく、
# 積み上がった結果の上限・下限をここで保証する）
SCORE_MIN = -10.0
SCORE_MAX = 10.0

# 候補日の近さ加点。候補日リストの先頭（=最も近い営業日）で最大、末尾で0になるよう線形補間する
PROXIMITY_BONUS_MAX = 3.0

# 始業(9:30)・終業(18:30)に近い枠への減点。このスロット数以内に入るほど強くなる
EDGE_OF_DAY_BUFFER_SLOTS = 2  # 1時間分
EDGE_OF_DAY_PENALTY_MAX = 2.0

# 前後どちらも空いている（30分バッファがある）枠への加点
ISOLATION_BONUS = 2.0
# 前後の予定に挟まれている枠への減点
ADJACENT_BUSY_PENALTY = 2.0

# 昼休憩(12:00〜13:00)にかぶる30分枠1つあたりの減点
LUNCH_OVERLAP_PENALTY_PER_SLOT = 1.5
# 昼休憩直後(13:00〜13:30)にかぶる30分枠1つあたりの減点
POST_LUNCH_PENALTY = 1.0

# 前後どちらかに2時間（120分）以上連続する予定ブロックができてしまう枠への減点
CONTINUOUS_BLOCK_THRESHOLD_MINUTES = 120
CONTINUOUS_BLOCK_BASE_PENALTY = 2.0
CONTINUOUS_BLOCK_EXTRA_PENALTY_PER_SLOT = 1.0

# 月曜・祝日明けの午前、金曜・祝日前の午後への減点
DAY_TRANSITION_MORNING_CUTOFF = dtime(12, 0)
DAY_TRANSITION_EVENING_CUTOFF = dtime(13, 0)
DAY_TRANSITION_PENALTY = 1.5


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


def _time_window_slot_indices(slots, window_start_time, window_end_time):
    """slots（1日分）のうち、指定した時刻区間（例: 昼休憩）と重なるスロットのインデックス集合を返す。"""
    indices = set()
    for i, (slot_start, slot_end) in enumerate(slots):
        window_start = slot_start.replace(
            hour=window_start_time.hour, minute=window_start_time.minute, second=0, microsecond=0
        )
        window_end = slot_start.replace(
            hour=window_end_time.hour, minute=window_end_time.minute, second=0, microsecond=0
        )
        if slot_start < window_end and slot_end > window_start:
            indices.add(i)
    return indices


def _is_day_off(date):
    """土日、または祝日ならTrue。"""
    return date.weekday() >= 5 or jpholiday.is_holiday(date)


def _day_transition_flags(date):
    """前日が休み（週末・祝日）なら午前を、翌日が休みなら午後を避けたい、というフラグを返す。
    月曜の前日は日曜（週末）なので自動的にday_before_off=Trueになる（祝日明けも同様）。"""
    day_before_off = _is_day_off(date - timedelta(days=1))
    day_after_off = _is_day_off(date + timedelta(days=1))
    return day_before_off, day_after_off


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


def fetch_context_snapshot(slack_user_id):
    """分析用データ（将来の機械学習利用）に添える特徴量スナップショットを取得する。
    前7日間と、先月同週（4週間前の週、月〜日）の予定の埋まり具合を返す。
    未連携・API失敗など何らかの理由で取得できない場合はNoneを返す（呼び出し元の処理は継続させる）。"""
    try:
        now = datetime.now(JST)

        prior_start = now - timedelta(days=7)
        prior_busy = _fetch_busy_intervals(slack_user_id, prior_start, now)

        last_month_ref = now - timedelta(days=28)  # 「先月同週」の近似として4週間前を採用
        week_start = datetime.combine(
            (last_month_ref - timedelta(days=last_month_ref.weekday())).date(), dtime.min, tzinfo=JST
        )
        week_end = week_start + timedelta(days=7)
        last_month_busy = _fetch_busy_intervals(slack_user_id, week_start, week_end)

        return {
            "prior_7_days": {
                "range": [prior_start.isoformat(), now.isoformat()],
                "busy": [[s.isoformat(), e.isoformat()] for s, e in prior_busy],
            },
            "same_week_last_month": {
                "range": [week_start.isoformat(), week_end.isoformat()],
                "busy": [[s.isoformat(), e.isoformat()] for s, e in last_month_busy],
            },
        }
    except Exception:
        logger.warning(f"コンテキストスナップショットの取得に失敗しました ({slack_user_id})", exc_info=True)
        return None


def is_slot_still_available(requester_id, partner_id, start, end):
    """候補提示からユーザーが選ぶまでの間に埋まっていないか、確定直前に再チェックする。"""
    slot = (start, end)
    requester_busy = _fetch_busy_intervals(requester_id, start, end)
    if _slot_is_busy(slot, requester_busy):
        return False

    partner_busy = _fetch_busy_intervals(partner_id, start, end)
    return not _slot_is_busy(slot, partner_busy)


def _directional_busy_minutes(busy_flags, start_idx, end_idx):
    """start_idx:end_idx（新規予定分）を仮にbusyとして重ねた場合に、その直前・直後それぞれに
    連続何分のbusyブロックができるかを(前, 後)のタプルで返す（新規予定自体の時間は含まない）。"""
    n = len(busy_flags)
    combined = list(busy_flags)
    for i in range(start_idx, end_idx):
        combined[i] = True

    left = start_idx
    while left - 1 >= 0 and combined[left - 1]:
        left -= 1
    before_minutes = (start_idx - left) * SLOT_MINUTES

    right = end_idx
    while right < n and combined[right]:
        right += 1
    after_minutes = (right - end_idx) * SLOT_MINUTES

    return before_minutes, after_minutes


def _continuous_block_penalty(busy_flags, start_idx, end_idx):
    """前後どちらかにCONTINUOUS_BLOCK_THRESHOLD_MINUTES以上の連続busyブロックができる場合の減点。
    前後は独立に判定するため、両側とも長時間ブロックになる枠は減点が二重にかかる（意図的）。"""
    penalty = 0.0
    for minutes in _directional_busy_minutes(busy_flags, start_idx, end_idx):
        if minutes >= CONTINUOUS_BLOCK_THRESHOLD_MINUTES:
            extra_slots = (minutes - CONTINUOUS_BLOCK_THRESHOLD_MINUTES) // SLOT_MINUTES
            penalty += CONTINUOUS_BLOCK_BASE_PENALTY + CONTINUOUS_BLOCK_EXTRA_PENALTY_PER_SLOT * extra_slots
    return penalty


def _edge_of_day_penalty(start_idx, end_idx, n_slots):
    """始業・終業に近い枠ほど強くなる減点（EDGE_OF_DAY_BUFFER_SLOTS以内が対象）。"""
    nearest_edge_distance = min(start_idx, n_slots - end_idx)
    if nearest_edge_distance >= EDGE_OF_DAY_BUFFER_SLOTS:
        return 0.0
    return EDGE_OF_DAY_PENALTY_MAX * (EDGE_OF_DAY_BUFFER_SLOTS - nearest_edge_distance) / EDGE_OF_DAY_BUFFER_SLOTS


def _isolation_bonus(requester_busy, partner_busy, start_idx, end_idx, n_slots):
    """前後どちらのスロットも（実在してかつ）空いている場合の加点。"""
    has_free_before = start_idx - 1 >= 0 and not (requester_busy[start_idx - 1] or partner_busy[start_idx - 1])
    has_free_after = end_idx < n_slots and not (requester_busy[end_idx] or partner_busy[end_idx])
    return ISOLATION_BONUS if has_free_before and has_free_after else 0.0


def _day_transition_penalty(slot_start, day_before_off, day_after_off):
    """月曜・祝日明けの午前、金曜・祝日前の午後を避けたい気持ちの減点。"""
    penalty = 0.0
    if day_before_off and slot_start.time() < DAY_TRANSITION_MORNING_CUTOFF:
        penalty += DAY_TRANSITION_PENALTY
    if day_after_off and slot_start.time() >= DAY_TRANSITION_EVENING_CUTOFF:
        penalty += DAY_TRANSITION_PENALTY
    return penalty


def _score_candidate(
    requester_busy,
    partner_busy,
    lunch_indices,
    post_lunch_indices,
    start_idx,
    end_idx,
    n_slots,
    days_from_now,
    slot_start,
    day_before_off,
    day_after_off,
):
    # 候補日リストの先頭（=最も近い営業日）ほど加点が大きく、末尾（CANDIDATE_BUSINESS_DAYS-1日後）で0になる
    score = PROXIMITY_BONUS_MAX * (1 - days_from_now / (CANDIDATE_BUSINESS_DAYS - 1))

    score -= _edge_of_day_penalty(start_idx, end_idx, n_slots)
    score += _isolation_bonus(requester_busy, partner_busy, start_idx, end_idx, n_slots)

    if start_idx - 1 >= 0 and (requester_busy[start_idx - 1] or partner_busy[start_idx - 1]):
        score -= ADJACENT_BUSY_PENALTY
    if end_idx < n_slots and (requester_busy[end_idx] or partner_busy[end_idx]):
        score -= ADJACENT_BUSY_PENALTY

    for busy_flags in (requester_busy, partner_busy):
        score -= _continuous_block_penalty(busy_flags, start_idx, end_idx)

    occupied_slots = set(range(start_idx, end_idx))
    score -= LUNCH_OVERLAP_PENALTY_PER_SLOT * len(occupied_slots & lunch_indices)
    score -= POST_LUNCH_PENALTY * len(occupied_slots & post_lunch_indices)

    score -= _day_transition_penalty(slot_start, day_before_off, day_after_off)

    return max(SCORE_MIN, min(SCORE_MAX, score))


def _generate_candidates(days, requester_busy_by_day, partner_busy_by_day, duration_minutes):
    duration_slots = duration_minutes // SLOT_MINUTES
    candidates = []

    for days_from_now, date in enumerate(days):
        slots = _day_slots(date)
        n_slots = len(slots)
        lunch_indices = _time_window_slot_indices(slots, LUNCH_START_TIME, LUNCH_END_TIME)
        post_lunch_indices = _time_window_slot_indices(slots, POST_LUNCH_START_TIME, POST_LUNCH_END_TIME)
        day_before_off, day_after_off = _day_transition_flags(date)
        requester_busy = requester_busy_by_day[date]
        partner_busy = partner_busy_by_day[date]

        for start_idx in range(0, n_slots - duration_slots + 1):
            end_idx = start_idx + duration_slots
            if any(requester_busy[start_idx:end_idx]) or any(partner_busy[start_idx:end_idx]):
                continue

            slot_start = slots[start_idx][0]
            score = _score_candidate(
                requester_busy,
                partner_busy,
                lunch_indices,
                post_lunch_indices,
                start_idx,
                end_idx,
                n_slots,
                days_from_now,
                slot_start,
                day_before_off,
                day_after_off,
            )
            candidates.append(
                {
                    "date": date,
                    "start": slot_start,
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
