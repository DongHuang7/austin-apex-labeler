"""
Austin Apex Label Server
Handles one-click label selections from email buttons.
Stores selections in PostgreSQL (Railway) — no Google credentials needed.
"""
import os
from datetime import datetime
from flask import Flask, jsonify, abort
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
VALID_LABELS = {"Buyer", "Seller", "Broker", "Other"}


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS selections (
                    session_id  TEXT NOT NULL,
                    contact_idx INTEGER NOT NULL,
                    category    TEXT NOT NULL,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (session_id, contact_idx)
                )
            """)
        conn.commit()


LABEL_COLORS = {
    "Buyer":  "#2980b9",
    "Seller": "#27ae60",
    "Broker": "#8e44ad",
    "Other":  "#7f8c8d",
}

def confirmation_page(contact_name, contact_email, category):
    color = LABEL_COLORS.get(category, "#264653")
    return f"""<!DOCTYPE html><html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Labeled ✓</title>
  <style>
    body {{ margin:0; font-family:Arial,sans-serif; background:#f5f5f5;
           display:flex; align-items:center; justify-content:center; min-height:100vh; }}
    .card {{ background:#fff; border-radius:12px; padding:40px 48px; text-align:center;
             box-shadow:0 2px 16px rgba(0,0,0,0.10); max-width:400px; width:90%; }}
    .check {{ font-size:56px; margin-bottom:16px; }}
    .label {{ display:inline-block; background:{color}; color:#fff;
              padding:8px 24px; border-radius:24px; font-size:18px;
              font-weight:bold; margin:12px 0; }}
    .name  {{ font-size:16px; color:#333; margin:8px 0 4px; font-weight:bold; }}
    .email {{ font-size:13px; color:#888; margin:0; }}
    .note  {{ font-size:12px; color:#bbb; margin-top:24px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="check">✓</div>
    <p class="name">{contact_name or contact_email}</p>
    <p class="email">{contact_email}</p>
    <div class="label">{category}</div>
    <p class="note">Label saved. You can close this tab.</p>
  </div>
</body>
</html>"""


@app.route("/label/<session_id>/<int:idx>/<category>/<name>/<path:email>")
def label(session_id, idx, category, name, email):
    """Called when a button is clicked in the review email."""
    category = category.capitalize()
    if category not in VALID_LABELS:
        abort(400, "Invalid category")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO selections (session_id, contact_idx, category)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id, contact_idx)
                DO UPDATE SET category = EXCLUDED.category, created_at = NOW()
            """, (session_id, idx, category))
        conn.commit()

    name = name.replace("_", " ")
    return confirmation_page(name, email, category)


@app.route("/selections/<session_id>")
def get_selections(session_id):
    """Called by the Mac script to retrieve corrections."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT contact_idx, category FROM selections WHERE session_id = %s",
                (session_id,)
            )
            rows = cur.fetchall()
    return jsonify({str(r["contact_idx"]): r["category"] for r in rows})


@app.route("/health")
def health():
    return "ok"


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
