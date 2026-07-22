import logging

from auth import google_oauth, token_store

logger = logging.getLogger(__name__)


def check_db():
    token_store.check_connection()
    logger.info("✅ DB接続: OK")


def check_slack(slack_app):
    resp = slack_app.client.auth_test()
    logger.info(f"✅ Slack接続: OK (bot: {resp['user']}, team: {resp['team']})")


def check_google():
    google_oauth.check_config()
    logger.info("✅ Google OAuth設定: OK")


def run_all_checks(slack_app):
    checks = [
        ("DB", check_db, True),
        ("Slack", lambda: check_slack(slack_app), True),
        ("Google", check_google, False),
    ]
    for name, fn, required in checks:
        try:
            fn()
        except Exception as e:
            if required:
                logger.error(f"❌ {name}接続チェックに失敗しました: {e}")
                raise
            logger.warning(f"⚠️ {name}設定チェックに失敗しました（Google連携機能は利用できません）: {e}")
