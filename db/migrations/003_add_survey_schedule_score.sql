-- 既存のDBボリューム（db/data）にはinit.sqlが再実行されないため、
-- 稼働中の環境には本ファイルを手動で適用してください。
-- 適用例: docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrations/003_add_survey_schedule_score.sql

ALTER TABLE one_on_one_surveys
    ADD COLUMN IF NOT EXISTS schedule_score INTEGER CHECK (schedule_score BETWEEN 0 AND 5);

COMMENT ON COLUMN one_on_one_surveys.schedule_score IS
    '実施後アンケート「日程のレコメンドはいかがでしたか」の回答（0:忙しくて迷惑だった 〜 5:ちょうどよかった）';
