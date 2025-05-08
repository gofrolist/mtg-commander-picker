import os
import json
import random
import requests
import gspread
from flask import Flask, request, jsonify
from flask_cors import CORS
from oauth2client.service_account import ServiceAccountCredentials

# ─── Flask app serving React build ─────────────────────────────────────────────
# static_folder="build" tells Flask to serve files out of /app/build
app = Flask(__name__, static_folder="build", static_url_path="/")
CORS(app)  # you can lock this down to your frontend’s domain in prod

# ─── Google Sheets Setup ────────────────────────────────────────────────────────
SCOPE = ['https://www.googleapis.com/auth/spreadsheets']
creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
if not creds_json:
    raise RuntimeError("Missing env var: GOOGLE_SHEETS_CREDENTIALS_JSON")
sheet_id = os.environ.get("GOOGLE_SHEET_ID")
if not sheet_id:
    raise RuntimeError("Missing env var: GOOGLE_SHEET_ID")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(sheet_id).sheet1

# Build header→column map dynamically
headers = sheet.row_values(1)
col_map = {h: i + 1 for i, h in enumerate(headers)}

# ─── Scryfall helper ────────────────────────────────────────────────────────────
def fetch_image_url(card_name: str) -> str:
    """Fetch the 'normal' image URL for a given card from Scryfall."""
    url = f"https://api.scryfall.com/cards/named?exact={requests.utils.quote(card_name)}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if 'image_uris' in data:
            uris = data['image_uris']
        elif data.get('card_faces'):
            uris = data['card_faces'][0].get('image_uris', {})
        else:
            uris = {}
        return uris.get('normal') or uris.get('large') or uris.get('small') or ""
    except Exception as e:
        app.logger.error(f"Scryfall error for '{card_name}': {e}")
        return ""

# ─── API ROUTES ─────────────────────────────────────────────────────────────────
@app.route('/api/cards', methods=['GET'])
def get_cards():
    color = request.args.get('color')
    if not color:
        return jsonify({"message": "Missing 'color' parameter"}), 400

    records = sheet.get_all_records()
    available = [
        r for r in records
        if str(r.get('Color')).strip().lower() == color.strip().lower()
           and not r.get('Status')
    ]
    if not available:
        return jsonify([])

    picks = random.sample(available, min(3, len(available)))
    return jsonify([
        {
            "name":  r.get('Card Name') or r.get('Name'),
            "image": fetch_image_url(r.get('Card Name') or r.get('Name'))
        }
        for r in picks
    ])


@app.route('/api/select-card', methods=['POST'])
def select_card():
    data = request.get_json(force=True)
    user = data.get('userName')
    card = data.get('cardName')
    color = data.get('cardColor')
    if not all([user, card, color]):
        return jsonify({"message": "Missing userName, cardName or cardColor"}), 400

    records = sheet.get_all_records()
    for idx, rec in enumerate(records, start=2):
        name   = rec.get('Card Name') or rec.get('Name')
        c      = rec.get('Color')
        status = rec.get('Status')
        if name == card and str(c).strip().lower() == color.strip().lower():
            if status:
                return jsonify({"message": "Card already reserved"}), 409
            sheet.update_cell(idx, col_map['Status'], "reserved")
            sheet.update_cell(idx, col_map['Reserved By'], user)
            return jsonify({"message": "success"})
    return jsonify({"message": "Card not found"}), 404


@app.route('/api/reset', methods=['POST'])
def reset_all():
    admin_secret = os.environ.get("ADMIN_SECRET")
    if not admin_secret or request.headers.get("X-Admin-Secret") != admin_secret:
        return jsonify({"message": "Unauthorized"}), 401

    records = sheet.get_all_records()
    updates = []
    for idx, rec in enumerate(records, start=2):
        if rec.get('Status') or rec.get('Reserved By'):
            updates.append({
                'range': f"{gspread.utils.rowcol_to_a1(idx, col_map['Status'])}",
                'values': [[""]]
            })
            updates.append({
                'range': f"{gspread.utils.rowcol_to_a1(idx, col_map['Reserved By'])}",
                'values': [[""]]
            })
    if updates:
        sheet.batch_update(updates)
    return jsonify({"message": "all reset"})


# ─── React catch‑all (serves index.html) ────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    # If the requested file exists in build/, serve it; otherwise serve index.html
    full_path = os.path.join(app.static_folder, path)
    if path and os.path.exists(full_path):
        return app.send_static_file(path)
    return app.send_static_file('index.html')


# ─── APP LAUNCH ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
