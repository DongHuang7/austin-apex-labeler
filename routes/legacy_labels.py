"""
One-click label-approval links from confirmation-digest emails
(run_monitor_new_contacts.py's send_confirmation_email). Ported as-is from
the original server/app.py, now using the shared SQLAlchemy models/session
instead of a standalone engine.
"""
from flask import Blueprint, abort, jsonify

from models import Selection, db

bp = Blueprint("legacy_labels", __name__)

VALID_LABELS = {"Buyer", "Seller", "Broker", "Other"}
LABEL_COLORS = {"Buyer": "#2980b9", "Seller": "#27ae60", "Broker": "#8e44ad", "Other": "#7f8c8d"}


def _confirmation_page(name, email, category):
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


@bp.route("/label/<session_id>/<int:idx>/<category>/<name>/<path:email>")
def label(session_id, idx, category, name, email):
    category = category.capitalize()
    if category not in VALID_LABELS:
        abort(400)

    row = Selection.query.filter_by(session_id=session_id, contact_idx=idx).first()
    if row is None:
        row = Selection(session_id=session_id, contact_idx=idx, category=category)
        db.session.add(row)
    else:
        row.category = category
    db.session.commit()

    return _confirmation_page(name.replace("_", " "), email, category)


@bp.route("/selections/<session_id>")
def get_selections(session_id):
    rows = Selection.query.filter_by(session_id=session_id).all()
    return jsonify({str(r.contact_idx): r.category for r in rows})


@bp.route("/health")
def health():
    return "ok"
