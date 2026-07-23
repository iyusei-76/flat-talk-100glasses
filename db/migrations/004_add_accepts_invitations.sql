-- 既存のDBボリューム（db/data）にはinit.sqlが再実行されないため、
-- 稼働中の環境には本ファイルを手動で適用してください。
-- 適用例: docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrations/004_add_accepts_invitations.sql

ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS accepts_invitations BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN user_profiles.accepts_invitations IS
    '1on1候補としての招待を受け付けるか（false ならカテゴリ抽選候補から除外される）';
