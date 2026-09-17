import requests
import json
import sqlite3
import os
import logging
from datetime import datetime

# --- KONFIGURASJON ---
# Bruk miljøvariabel for Slack Webhook URL slik at den ikke havner åpent på GitHub
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_MATTILSYNET") 
DB_PATH = "recalls.db"
URL = "https://www.mattilsynet.no/tilbakekallinger/__data.json?category=&search=&index=1&x-sveltekit-invalidated=01"

# Sett opp enkel logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def init_db():
    """Setter opp en enkel SQLite-database for å huske hvilke tilbakekallinger vi har sett."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Bruker URL eller en unik ID fra Mattilsynet som primary key
    c.execute('''CREATE TABLE IF NOT EXISTS recalls (id TEXT PRIMARY KEY, title TEXT, date_added TEXT)''')
    conn.commit()
    conn.close()

def is_new_recall(recall_id):
    """Sjekker om en tilbakekalling allerede finnes i basen."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM recalls WHERE id=?", (recall_id,))
    result = c.fetchone()
    conn.close()
    return result is None

def save_recall(recall_id, title):
    """Lagrer en ny tilbakekalling i basen."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    date_added = datetime.now().isoformat()
    c.execute("INSERT INTO recalls (id, title, date_added) VALUES (?, ?, ?)", (recall_id, title, date_added))
    conn.commit()
    conn.close()

def fetch_data():
    """Henter data fra Mattilsynet."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(URL, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Feil ved henting av data fra Mattilsynet: {e}")
        return None

def deref(val, flat, visited=None):
    """Oppløser SvelteKit sine indeks-pekere til faktiske verdier."""
    if visited is None:
        visited = set()
    if isinstance(val, int) and 0 <= val < len(flat):
        if val in visited:
            return None
        visited.add(val)
        return deref(flat[val], flat, visited)
    if isinstance(val, dict):
        return {k: deref(v, flat, visited.copy()) for k, v in val.items()}
    if isinstance(val, list):
        return [deref(v, flat, visited.copy()) for v in val]
    return val

def resolve_val(val, flat_data):
    """Henter ut den faktiske strengen eller verdien hvis val er en indeks-peker."""
    if isinstance(val, int) and 0 <= val < len(flat_data):
        target = flat_data[val]
        if isinstance(target, int):
            return resolve_val(target, flat_data)
        return target
    return val

def extract_recalls(data):
    recalls = []
    seen = set()
    
    try:
        flat = data['nodes'][1]['data']
        
        for item in flat:
            if isinstance(item, dict):
                # Slå opp faktiske verdier bak indeks-pekerne
                raw_path = item.get("_path") or item.get("url") or item.get("href")
                raw_title = item.get("title") or item.get("displayName")
                
                path = resolve_val(raw_path, flat)
                title = resolve_val(raw_title, flat)
                
                if isinstance(path, str) and isinstance(title, str):
                    # Sjekk at dette er en undersak og ikke selve hovedsiden
                    if "tilbakekallinger/" in path and path.rstrip('/') not in ["/tilbakekallinger", "/mattilsynet/tilbakekallinger"]:
                        clean_path = path.replace('/mattilsynet', '')
                        
                        if clean_path not in seen:
                            seen.add(clean_path)
                            recalls.append({
                                "id": clean_path,
                                "tittel": title.strip(),
                                "url": f"https://www.mattilsynet.no{clean_path}",
                                "kategori": "Mat og drikke"
                            })
    except Exception as e:
        logging.error(f"Feil under parsing av SvelteKit-matrisen: {e}")
        
    return recalls

def send_slack_notification(recall):
    """Sender et varsel til Slack med Block Kit for å se proft ut."""
    if not SLACK_WEBHOOK_URL:
        logging.error("SLACK_WEBHOOK_MATTILSYNET miljøvariabel mangler!")
        return
        
    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 Ny tilbakekalling fra Mattilsynet",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{recall['tittel']}*\nKategori: {recall['kategori']}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Les saken hos Mattilsynet",
                            "emoji": True
                        },
                        "value": "click_me",
                        "url": recall['url'],
                        "action_id": "button-action"
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        logging.info(f"Sendte varsel til Slack om: {recall['tittel']}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Feil ved sending til Slack: {e}")

def main():
    init_db()
    data = fetch_data()
    
    if data:
        recalls = extract_recalls(data)
        
        if not recalls:
            logging.warning("Fant ingen tilbakekallinger i dataene. Sjekk extract_recalls-logikken.")
            
        for recall in recalls:
            if is_new_recall(recall['id']):
                logging.info(f"Fant NY tilbakekalling: {recall['tittel']}")
                send_slack_notification(recall)
                save_recall(recall['id'], recall['tittel'])
            else:
                pass # logging.debug(f"Kjent tilbakekalling: {recall['tittel']}")

if __name__ == "__main__":
    main()
