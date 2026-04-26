"""Flask application factory.

Composition only: build the Flask app, attach JWT, install blueprints, and
register error handlers. Database access is delegated to :mod:`shared.db` so
the worker processes can use the same persistence layer without importing
Flask.
"""

from __future__ import annotations

from flask import Flask

from shared.config import get_settings
from shared.observability import configure_logging

from .error_handlers import register_error_handlers
from .extensions import jwt
from .routes import alerts_bp, auth_bp, health_bp, predict_bp, stats_bp


def create_app() -> Flask:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["JWT_SECRET_KEY"] = settings.jwt_secret_key
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MiB

    jwt.init_app(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(stats_bp)

    register_error_handlers(app)

    return app
