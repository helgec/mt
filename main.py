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

def extract_recalls(data):
    """
    Trekker ut tilbakekallinger fra SvelteKit sin JSON-struktur.
    VIKTIG: Denne funksjonen må du tilpasse basert på hvordan JSON-en din ser ut.
    SvelteKit data.json ser ofte slik ut: {"type":"data", "nodes":[...]} og 
    har data lagret i en array (ofte indexert).
    
    Dette er en eksempel-implementasjon som antar at du har funnet listen med 
    objekter et sted i strukturen.
    """
    recalls = []
    
    # --- TIPS FOR FEILSØKING ---
    # Print ut 'data' her eller lagre den til fil midlertidig mens du utvikler 
    # for å finne nøyaktig sti til tittel, URL/ID osv.
    # print(json.dumps(data, indent=2))
    
    try:
        # Eksempel på navigering i en fiktiv (men vanlig) SvelteKit struktur:
        # Ofte ligger dataene under data["nodes"][1]["data"] 
        # Siden vi vet det er et flatet format, må vi ofte "hoppe" litt.
        
        # Her later vi som vi har fått ut en flat liste med saker som dette:
        # [{"id": "sjømathuset", "tittel": "Sjømathuset AS tilbakekaller laks", "url": "/tilbakekallinger/sjomathuset"}]
        
        # BYTT UT DETTE med faktisk logikk for å finne arrayen med tilbakekallinger i 'data'
        items_from_json = [] # Fyll denne med den faktiske listen fra 'data'
        
        for item in items_from_json:
            recalls.append({
                "id": item.get("url"), # URL fungerer ofte bra som unik ID
                "tittel": item.get("title", "Ukjent tittel"),
                "url": f"https://www.mattilsynet.no{item.get('url')}", # Legg til base-URL hvis den mangler
                "kategori": item.get("category", "Ikke oppgitt")
            })
    except Exception as e:
        logging.error(f"Klarte ikke parse JSON-strukturen: {e}")
        
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
