"""Flask extensions used by the API service.

Persistence is intentionally **not** managed through Flask-SQLAlchemy. Routes
talk to the database via :mod:`shared.db.session_scope`, which works
identically inside Flask request handlers and in headless workers.
"""

from flask_jwt_extended import JWTManager

jwt = JWTManager()
