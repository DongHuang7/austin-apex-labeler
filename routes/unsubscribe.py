from flask import Blueprint, render_template, request

from models import Suppression, db
from unsubscribe_tokens import verify_token

bp = Blueprint("unsubscribe", __name__)


@bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    """Public on purpose — clicked from an inbox, not the logged-in app.
    GET only shows a confirm page (never acts on its own) since email
    clients/security scanners routinely pre-fetch links in emails; only the
    POST from clicking the confirm button actually unsubscribes."""
    email = verify_token(token)
    if not email:
        return render_template("unsubscribe.html", invalid=True), 400

    if request.method == "POST":
        if not Suppression.query.filter_by(email=email).first():
            db.session.add(Suppression(email=email))
            db.session.commit()
        return render_template("unsubscribe.html", email=email, done=True)

    already = Suppression.query.filter_by(email=email).first() is not None
    return render_template("unsubscribe.html", email=email, already=already)
