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