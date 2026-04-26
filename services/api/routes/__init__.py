from .alerts import alerts_bp
from .auth import auth_bp
from .health import health_bp
from .predict import predict_bp
from .stats import stats_bp

__all__ = ["alerts_bp", "auth_bp", "health_bp", "predict_bp", "stats_bp"]
