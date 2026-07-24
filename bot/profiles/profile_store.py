from datetime import datetime

import db


def current_fiscal_year():
    """日本の会計年度（4月始まり）基準の「今の年度」"""
    now = datetime.now()
    return now.year if now.month >= 4 else now.year - 1


def save_user_profile(slack_user_id, join_year, hire_type):
    with db.get_auth_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_profiles
                    (slack_user_id, join_year, hire_type, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (slack_user_id) DO UPDATE SET
                    join_year = EXCLUDED.join_year,
                    hire_type = EXCLUDED.hire_type,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (slack_user_id, join_year, hire_type),
            )
        conn.commit()


def get_user_profile(slack_user_id):
    with db.get_auth_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT join_year, hire_type, accepts_invitations
                FROM user_profiles
                WHERE slack_user_id = %s
                """,
                (slack_user_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return {"join_year": row[0], "hire_type": row[1], "accepts_invitations": row[2]}


def set_accepts_invitations(slack_user_id, accepts):
    with db.get_auth_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_profiles
                SET accepts_invitations = %s, updated_at = CURRENT_TIMESTAMP
                WHERE slack_user_id = %s
                """,
                (accepts, slack_user_id),
            )
        conn.commit()


def get_candidate_slack_user_ids(category, current_fiscal_year_value, exclude_user_id=None):
    if category == "new_grad":
        # 新卒: 今の年度に入社した新卒
        condition = "hire_type = 'new_grad' AND join_year = %s"
        params = [current_fiscal_year_value]
    elif category == "mid_career":
        # 中途: 勤続年数が2年未満の中途入社者
        condition = "hire_type = 'mid_career' AND (%s - join_year) < 2"
        params = [current_fiscal_year_value]
    elif category == "existing":
        # 既存社員: 新卒は勤続1年以上、中途は勤続2年以上
        condition = "(hire_type = 'new_grad' AND (%s - join_year) >= 1) OR (hire_type = 'mid_career' AND (%s - join_year) >= 2)"
        params = [current_fiscal_year_value, current_fiscal_year_value]
    elif category == "any":
        # 指定しない: カテゴリで絞り込まず登録済み全員から選ぶ
        condition = None
        params = []
    else:
        raise ValueError(f"未知のカテゴリです: {category}")

    conditions = [f"({condition})"] if condition else []
    conditions.append("accepts_invitations")
    if exclude_user_id:
        conditions.append("slack_user_id != %s")
        params.append(exclude_user_id)

    query = "SELECT slack_user_id FROM user_profiles"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    with db.get_auth_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return [row[0] for row in rows]
