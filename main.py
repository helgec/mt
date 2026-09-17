import os
import sqlite3
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# --- KONFIGURASJON ---
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_MATTILSYNET")
DB_PATH = "recalls.db"
BASE_URL = "https://www.mattilsynet.no"
TARGET_URL = f"{BASE_URL}/tilbakekallinger"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def init_db():
    """Oppretter SQLite-databasen dersom den ikke eksisterer."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS recalls (id TEXT PRIMARY KEY, title TEXT, date_added TEXT)''')

def is_new_recall(recall_id):
    """Sjekker om saken allerede er registrert i basen."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM recalls WHERE id=?", (recall_id,))
        return cursor.fetchone() is None

def save_recall(recall_id, title):
    """Lagrer ny sak i databasen."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO recalls (id, title, date_added) VALUES (?, ?, ?)",
                     (recall_id, title, datetime.now().isoformat()))

def fetch_recalls():
    """Henter og parser HTML direkte fra Mattilsynets tilbakekallingsside."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    recalls = []
    seen_ids = set()

    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Finn alle lenker som peker til enkeltsaker
        for link in soup.find_all('a', href=True):
            href = link['href']
            title = link.get_text(strip=True)

            if '/tilbakekallinger/' in href and href.rstrip('/') not in ['/tilbakekallinger', '/mattilsynet/tilbakekallinger']:
                clean_id = href.replace('/mattilsynet', '')
                
                if title and len(title) > 5 and clean_id not in seen_ids:
                    seen_ids.add(clean_id)
                    recalls.append({
                        "id": clean_id,
                        "tittel": title,
                        "url": f"{BASE_URL}{clean_id}" if clean_id.startswith('/') else clean_id,
                        "kategori": "Mat og drikke"
                    })
    except requests.exceptions.RequestException as e:
        logging.error(f"Feil ved henting fra Mattilsynet: {e}")

    return recalls

def send_slack_notification(recall):
    """Sender Slack-varsel med Block Kit-oppsett."""
    if not SLACK_WEBHOOK_URL:
        logging.error("SLACK_WEBHOOK_MATTILSYNET miljøvariabel mangler!")
        return

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🚨 Ny tilbakekalling fra Mattilsynet", "emoji": True}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{recall['tittel']}*\nKategori: {recall['kategori']}"}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Les saken hos Mattilsynet", "emoji": True},
                        "url": recall['url'],
                        "action_id": "button-action"
                    }
                ]
            }
        ]
    }

    try:
        res = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        res.raise_for_status()
        logging.info(f"Sendte varsel til Slack om: {recall['tittel']}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Feil ved sending til Slack: {e}")

def main():
    init_db()
    recalls = fetch_recalls()

    if not recalls:
        logging.warning("Fant ingen tilbakekallinger på nettsiden. Sjekk om selectors må oppdateres.")
        return

    for recall in recalls:
        if is_new_recall(recall['id']):
            logging.info(f"Fant NY tilbakekalling: {recall['tittel']}")
            send_slack_notification(recall)
            save_recall(recall['id'], recall['tittel'])

if __name__ == "__main__":
    main()
