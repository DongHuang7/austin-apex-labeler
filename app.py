"""
Austin Apex internal dashboard.
Replaces the original one-route label-approval server with the full
dashboard: login, contact review inbox, campaign composer, plus the
original one-click label-approval links (routes/legacy_labels.py) and the
Google OAuth connect flow (routes/oauth.py).
"""
import os

import click
from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash

load_dotenv()

from models import User, db  # noqa: E402


def _database_url() -> str:
    url = os.environ["DATABASE_URL"]
    # Heroku's DATABASE_URL uses the postgres:// scheme; SQLAlchemy 1.4+/2.x
    # requires postgresql://, and pg8000 (pure-Python, no C build deps) needs
    # the +pg8000 dialect suffix.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and "+pg8000" not in url:
        url = url.replace("postgresql://", "postgresql+pg8000://", 1)
    return url


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
    app.config["SQLALCHEMY_DATABASE_URI"] = _database_url()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

    db.init_app(app)
    Migrate(app, db)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from routes.auth import bp as auth_bp
    from routes.campaigns import bp as campaigns_bp
    from routes.contacts import bp as contacts_bp
    from routes.dashboard import bp as dashboard_bp
    from routes.legacy_labels import bp as legacy_labels_bp
    from routes.oauth import bp as oauth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(legacy_labels_bp)

    @app.cli.command("create-user")
    @click.argument("email")
    @click.argument("display_name")
    @click.password_option()
    def create_user(email, display_name, password):
        """Seed a dashboard login, e.g.:
        flask create-user yifan@austinapexre.com "Yifan Ingle" """
        if User.query.filter_by(email=email.lower()).first():
            click.echo(f"User {email} already exists.")
            return
        user = User(
            email=email.lower(),
            display_name=display_name,
            # pbkdf2 (not Werkzeug's newer scrypt default) since it needs no
            # OpenSSL scrypt support — safest against varying buildpack OpenSSL builds.
            password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created user {email}.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
