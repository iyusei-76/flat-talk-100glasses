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