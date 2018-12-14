from pathlib import Path

KIDCONNECT_LOGIN="your_email@kidconnect.pl"
KIDCONNECT_PASSWORD="YourPassword12345"
IFTTT_KEY="Get it from https://ifttt.com/services/maker_webhooks/settings"
HISTORY_FILE=Path(__file__).parent.joinpath('history.json')  # Where to store the news history (so you don't get double-notified)"
CONVERSATIONS={}  # {id: title} map for tracked conversations. Get the ID from the KidConnect URL.
