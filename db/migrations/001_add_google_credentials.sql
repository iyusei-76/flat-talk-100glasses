-- 既存のDBボリューム（db/data）にはinit.sqlが再実行されないため、
-- 稼働中の環境には本ファイルを手動で適用してください。
-- 適用例: docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrations/001_add_google_credentials.sql

CREATE TABLE IF NOT EXISTS google_credentials (
    slack_user_id VARCHAR(50) PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry TIMESTAMP WITH TIME ZONE,
    scope TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
