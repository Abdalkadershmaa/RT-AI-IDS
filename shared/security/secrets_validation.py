"""Refuse to start in production with placeholder secrets."""

from __future__ import annotations

DEFAULT_SENTINELS = frozenset(
    {
        "change-me-in-production",
        "change-me",
        "changeme",
        "secret",
        "password",
    }
)


class InsecureDefaultSecretError(RuntimeError):
    """Raised when production starts with placeholder secrets."""


def validate_runtime_secrets(
    *,
    environment: str,
    secret_key: str,
    jwt_secret_key: str,
    admin_password: str,
    extra_sentinels: frozenset[str] = frozenset(),
) -> None:
    """Fail-fast if a non-development env still uses the example secrets.

    ``environment`` is compared case-insensitively. The check is bypassed only
    when ``environment`` starts with ``dev`` or equals ``test``.
    """

    env = (environment or "").strip().lower()
    if env.startswith("dev") or env == "test":
        return

    sentinels = DEFAULT_SENTINELS | set(extra_sentinels)
    offending: list[str] = []
    if secret_key.lower() in sentinels:
        offending.append("SECRET_KEY")
    if jwt_secret_key.lower() in sentinels:
        offending.append("JWT_SECRET_KEY")
    if admin_password.lower() in sentinels:
        offending.append("ADMIN_PASSWORD")

    if offending:
        joined = ", ".join(offending)
        raise InsecureDefaultSecretError(
            "Refusing to start: insecure default value(s) detected for: "
            f"{joined}. Set ENVIRONMENT=development to bypass for local work, "
            "or run `make bootstrap` to generate safe values."
        )
