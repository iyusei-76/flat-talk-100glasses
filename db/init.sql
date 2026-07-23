CREATE TABLE IF NOT EXISTS message_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Google OAuthトークン保存用（ログイン/連携データ）
-- access_token / refresh_token はアプリ側でGOOGLE_TOKEN_ENCRYPTION_KEYを使って暗号化してから保存する
CREATE TABLE IF NOT EXISTS google_credentials (
    slack_user_id VARCHAR(50) PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry TIMESTAMP WITH TIME ZONE,
    scope TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ユーザープロフィール（入社年度・新卒/中途）保存用
-- Google連携完了後に表示する「登録」ボタン→モーダルから入力される
CREATE TABLE IF NOT EXISTS user_profiles (
    slack_user_id VARCHAR(50) PRIMARY KEY,
    join_year INTEGER NOT NULL,
    hire_type VARCHAR(20) NOT NULL CHECK (hire_type IN ('new_grad', 'mid_career')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 1on1の分析用データ（将来の機械学習利用を想定）
-- アプリ側（bot/analytics/store.py）でも起動時にCREATE TABLE IF NOT EXISTSしているため、
-- 既にデータボリュームが存在する既存環境でもここを変更しなくてよい（新規構築時用）。

-- 1on1候補提示（スコアリング）1回分
CREATE TABLE IF NOT EXISTS one_on_one_attempts (
    id SERIAL PRIMARY KEY,
    requester_id VARCHAR(50) NOT NULL,
    partner_id VARCHAR(50) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    context_snapshot JSONB, -- 前7日間 / 先月同週の空き状況スナップショット（特徴量用）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 提示した候補枠それぞれのスコアと、実際に選ばれたかどうか
CREATE TABLE IF NOT EXISTS one_on_one_candidate_slots (
    id SERIAL PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES one_on_one_attempts(id),
    rank_order INTEGER NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    score NUMERIC NOT NULL,
    is_selected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 実際にGoogleカレンダーへ登録されたイベントと、その後の状況（変更・キャンセル・実施有無）
CREATE TABLE IF NOT EXISTS one_on_one_events (
    id SERIAL PRIMARY KEY,
    candidate_slot_id INTEGER REFERENCES one_on_one_candidate_slots(id),
    requester_id VARCHAR(50) NOT NULL,
    partner_id VARCHAR(50) NOT NULL,
    google_event_id TEXT,
    original_start TIMESTAMP WITH TIME ZONE NOT NULL,
    original_end TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'rescheduled', 'cancelled', 'held', 'no_show')),
    last_checked_start TIMESTAMP WITH TIME ZONE,
    last_checked_end TIMESTAMP WITH TIME ZONE,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 実施後アンケート結果（?surveyコマンドから送信）
CREATE TABLE IF NOT EXISTS one_on_one_surveys (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES one_on_one_events(id),
    slack_user_id VARCHAR(50) NOT NULL,
    held BOOLEAN,
    feedback TEXT,
    -- 「日程のレコメンドはいかがでしたか」の回答（0:忙しくて迷惑だった 〜 5:ちょうどよかった）
    schedule_score INTEGER CHECK (schedule_score BETWEEN 0 AND 5),
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);