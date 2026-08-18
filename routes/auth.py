from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from models import User, db

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    user = User.query.filter_by(email=email).first()
    if user is None or not check_password_hash(user.password_hash, password):
        return render_template("login.html", error="Wrong email or password."), 401

    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()
    login_user(user, remember=True)
    return redirect(url_for("dashboard.home"))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("change_password.html")

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(current_user.password_hash, current_password):
        return render_template("change_password.html", error="Current password is wrong."), 401
    if len(new_password) < 8:
        return render_template("change_password.html", error="New password must be at least 8 characters."), 400
    if new_password != confirm_password:
        return render_template("change_password.html", error="New passwords don't match."), 400

    current_user.password_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
    db.session.commit()
    flash("Password updated.")
    return redirect(url_for("dashboard.home"))
