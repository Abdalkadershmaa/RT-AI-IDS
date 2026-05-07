"""Flask application factory.

Composition only: build the Flask app, attach JWT + rate limiter, install
blueprints, register error handlers, and register CLI commands. Database
access is delegated to :mod:`shared.db` so the worker processes can use the
same persistence layer without importing Flask.
"""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from shared.config import get_settings
from shared.observability import configure_logging
from shared.observability.tracing import (
    configure_tracing,
    instrument_flask,
)

from .cli import register_cli
from .error_handlers import register_error_handlers
from .extensions import init_limiter, jwt
from .middleware import install_metrics_middleware
from .routes import (
    alerts_bp,
    auth_bp,
    health_bp,
    metrics_bp,
    pipeline_bp,
    predict_bp,
    stats_bp,
)


def create_app() -> Flask:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        service=settings.service_name,
        schema_version=settings.log_schema_version,
    )
    configure_tracing(
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
    )

    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["JWT_SECRET_KEY"] = settings.jwt_secret_key
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MiB

    # CORS: explicit allow-list from CORS_ALLOW_ORIGINS env var. The frontend
    # cannot read JWT-protected responses without Access-Control-Allow-Origin
    # being one of the configured origins. Wildcard ("*") is intentionally
    # disallowed when credentials are involved; operators must list each
    # origin (e.g. https://soc.example.com,https://localhost:5173).
    allowed_origins = list(settings.cors_allow_origins)
    if allowed_origins:
        CORS(
            app,
            resources={r"/api/*": {"origins": allowed_origins}},
            supports_credentials=True,
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["Content-Type"],
            methods=["DELETE", "GET", "POST", "OPTIONS"],
            max_age=600,
        )

    jwt.init_app(app)
    init_limiter(app)
    install_metrics_middleware(app)
    instrument_flask(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(stats_bp)

    register_error_handlers(app)
    register_cli(app)

    return app
