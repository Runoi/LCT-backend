"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend service.

    Attributes:
        database_url: Async SQLAlchemy connection string (postgresql+asyncpg://...).
        app_env: Deployment environment name (e.g. "local", "docker", "production").
        log_level: Logging verbosity level name.
        replay_speed_multiplier: How many virtual seconds pass per wall-clock
            second in the SMVU replay engine (see ticket 06, ADR 0005).
        replay_tick_seconds: Wall-clock interval between replay engine ticks.
        ml_predictor_url: Root URL of an externally-deployed ML Prediction
            Port implementation (ticket 08, ADR 0006). When unset, the
            backend falls back to the in-process StubPredictor -- swapping
            in a real model never requires a backend code change.
        session_ttl_minutes: Lifetime of a login session; an expired
            bearer token is rejected with 401 SESSION_EXPIRED.
        login_max_failures_per_username: Failed logins for one username
            inside the window that lock further attempts (429).
        login_max_failures_per_ip: Same limit per client IP; higher so an
            office behind one NAT is not locked by a few typos.
        login_failure_window_seconds: Sliding window for both limits.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://mkl:mkl@localhost:5432/mkl"
    app_env: str = "local"
    log_level: str = "INFO"
    replay_speed_multiplier: float = 360.0
    replay_tick_seconds: float = 5.0
    ml_predictor_url: str | None = None
    session_ttl_minutes: int = 480
    login_max_failures_per_username: int = 5
    login_max_failures_per_ip: int = 20
    login_failure_window_seconds: int = 900


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance.

    Returns:
        The process-wide Settings singleton.
    """
    return Settings()
