-- 既存のDBボリューム（db/data）にはinit.sqlが再実行されないため、
-- 稼働中の環境には本ファイルを手動で適用してください。
-- 適用例: docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrations/002_add_user_profiles.sql

CREATE TABLE IF NOT EXISTS user_profiles (
    slack_user_id VARCHAR(50) PRIMARY KEY,
    join_year INTEGER NOT NULL,
    hire_type VARCHAR(20) NOT NULL CHECK (hire_type IN ('new_grad', 'mid_career')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
