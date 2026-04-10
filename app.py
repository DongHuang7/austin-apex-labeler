"""
Austin Apex Label Server
Handles one-click label selections from email buttons.
"""
import os
from flask import Flask, abort, jsonify
from sqlalchemy import create_engine, text

app = Flask(__name__)

# pg8000 is pure Python — no native libs needed
_url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql+pg8000://", 1)
if "postgresql://" in _url and "+pg8000" not in _url:
    _url = _url.replace("postgresql://", "postgresql+pg8000://", 1)

engine = create_engine(_url)

VALID_LABELS = {"Buyer", "Seller", "Broker", "Other"}
LABEL_COLORS = {"Buyer": "#2980b9", "Seller": "#27ae60", "Broker": "#8e44ad", "Other": "#7f8c8d"}


def init_db():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS selections (
                session_id  TEXT NOT NULL,
                contact_idx INTEGER NOT NULL,
                category    TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (session_id, contact_idx)
            )
        """))
        conn.commit()


def confirmation_page(name, email, category):
    color = LABEL_COLORS.get(category, "#264653")
    return f"""<!DOCTYPE html><html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Labeled</title>
  <style>
    body{{margin:0;font-family:Arial,sans-serif;background:#f5f5f5;
         display:flex;align-items:center;justify-content:center;min-height:100vh;}}
    .card{{background:#fff;border-radius:12px;padding:40px 48px;text-align:center;
           box-shadow:0 2px 16px rgba(0,0,0,.1);max-width:380px;width:90%;}}
    .check{{font-size:56px;margin-bottom:16px;}}
    .badge{{display:inline-block;background:{color};color:#fff;padding:8px 24px;
            border-radius:24px;font-size:18px;font-weight:bold;margin:12px 0;}}
    .name{{font-size:16px;color:#333;margin:8px 0 4px;font-weight:bold;}}
    .email{{font-size:13px;color:#888;margin:0;}}
    .note{{font-size:12px;color:#bbb;margin-top:24px;}}
  </style>
</head>
<body>
  <div class="card">
    <div class="check">✓</div>
    <p class="name">{name or email}</p>
    <p class="email">{email}</p>
    <div class="badge">{category}</div>
    <p class="note">Label saved. You can close this tab.</p>
  </div>
</body></html>"""


@app.route("/label/<session_id>/<int:idx>/<category>/<name>/<path:email>")
def label(session_id, idx, category, name, email):
    category = category.capitalize()
    if category not in VALID_LABELS:
        abort(400)
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO selections (session_id, contact_idx, category)
            VALUES (:sid, :idx, :cat)
            ON CONFLICT (session_id, contact_idx)
            DO UPDATE SET category = EXCLUDED.category, created_at = NOW()
        """), {"sid": session_id, "idx": idx, "cat": category})
        conn.commit()
    return confirmation_page(name.replace("_", " "), email, category)


@app.route("/selections/<session_id>")
def get_selections(session_id):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT contact_idx, category FROM selections WHERE session_id = :sid"
        ), {"sid": session_id}).fetchall()
    return jsonify({str(r[0]): r[1] for r in rows})


@app.route("/health")
def health():
    return "ok"


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
