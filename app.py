"""
Austin Apex internal dashboard.
Replaces the original one-route label-approval server with the full
dashboard: login, contact review inbox, campaign composer, social post
composer (routes/social.py), plus the original one-click label-approval
links (routes/legacy_labels.py) and the Google OAuth connect flow
(routes/oauth.py).
"""
import os

import click
from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix
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
    # Railway (and Heroku) terminate TLS at the edge and forward plain HTTP
    # to the container — without this, url_for(..., _external=True) and the
    # OAuth redirect_uri it builds come out as http://, which Google rejects
    # since the registered redirect URI is https://.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.config["SECRET_KEY"] = os.environ["FLASK_SECRET_KEY"]
    app.config["SQLALCHEMY_DATABASE_URI"] = _database_url()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    # Needed to build absolute URLs (e.g. the unsubscribe link embedded in
    # each sent email) from contexts with no incoming HTTP request to infer
    # a host from — the scheduled-send scripts under scripts/, and the
    # dashboard-load check in scheduler.py when it's not itself handling
    # that specific request.
    app.config["APP_BASE_URL"] = os.environ.get("APP_BASE_URL", "http://localhost:5000")

    db.init_app(app)
    Migrate(app, db)

    from timeutil import to_local
    app.jinja_env.filters["localtime"] = to_local

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
    from routes.social import bp as social_bp
    from routes.unsubscribe import bp as unsubscribe_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(legacy_labels_bp)
    app.register_blueprint(unsubscribe_bp)

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

    @app.cli.command("reset-password")
    @click.argument("email")
    @click.password_option()
    def reset_password(email, password):
        """Reset an existing dashboard login's password, e.g.:
        flask reset-password yifan@austinapexre.com"""
        user = User.query.filter_by(email=email.lower()).first()
        if user is None:
            click.echo(f"No user {email}.")
            return
        user.password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        db.session.commit()
        click.echo(f"Reset password for {email}.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
