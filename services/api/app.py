from flask import Flask, jsonify
from flask_jwt_extended import jwt_required

from shared.config import get_settings
from shared.logging_utils import configure_logging

from .extensions import db, jwt
from .routes import alerts_bp, auth_bp, health_bp, predict_bp


def create_app() -> Flask:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["JWT_SECRET_KEY"] = settings.jwt_secret_key

    db.init_app(app)
    jwt.init_app(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(predict_bp)

    @app.get("/api/v1/stats")
    @jwt_required()
    def stats() -> tuple:
        from .models import AttackLog

        total_alerts = AttackLog.query.count()
        by_risk = (
            db.session.query(AttackLog.risk_label, db.func.count(AttackLog.id))
            .group_by(AttackLog.risk_label)
            .all()
        )
        return jsonify(
            {
                "total_alerts": total_alerts,
                "risk_distribution": {label: count for label, count in by_risk},
            }
        ), 200

    @app.errorhandler(400)
    def bad_request(_error):
        return jsonify({"error": "bad_request"}), 400

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify({"error": "internal_server_error"}), 500

    with app.app_context():
        db.create_all()

    return app

