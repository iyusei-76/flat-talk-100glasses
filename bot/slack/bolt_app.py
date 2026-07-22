import os

from slack_bolt import App

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))
