from bs4 import BeautifulSoup
import feedparser
import firebase_admin
from firebase_admin import credentials, messaging
import json
import os
import re

RSS_URL = os.environ["FETCHRSS_URL"]
STATE_FILE = "state/last_fb_post.json"
FCM_TOPIC = os.environ.get("FCM_TOPIC", "smtt_actus")


def clean_description(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    for tag in soup.find_all("span"):
        if "Generated with" in tag.get_text() or "FetchRSS" in tag.get_text():
            tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180] + ("…" if len(text) > 180 else "")


def init_firebase():
    if not firebase_admin._apps:
        service_account_info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT_JSON"])
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)


def main():
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        raise RuntimeError("Aucun item trouvé dans le flux FetchRSS.")

    latest = feed.entries[0]
    post_id = latest.get("id") or latest.get("link")
    title = (latest.get("title") or "Nouvelle actu Stade Montois TT").strip()
    link = (latest.get("link") or "https://www.facebook.com/stademontoistt").strip()
    body = clean_description(latest.get("description", "")) or title

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    last_id = None
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            last_id = json.load(f).get("last_id")

    if post_id != last_id:
        init_firebase()
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"SMTT · {title}"[:80],
                body=body,
            ),
            data={"url": link, "source": "facebook"},
            topic=FCM_TOPIC,
        )
        response = messaging.send(message)
        print(f"Notification envoyée (ID FCM: {response}) pour le post {post_id}")

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_id": post_id, "last_title": title}, f, ensure_ascii=False, indent=2)
    else:
        print("Aucun nouveau post Facebook depuis le dernier contrôle.")


if __name__ == "__main__":
    main()
