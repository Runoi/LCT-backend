"""Password hashing and server-side session management (mock LDAP/AD)."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.auth import User, UserSession

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Hash a password with a random salt using PBKDF2-HMAC-SHA256.

    Args:
        password: The plain-text password to hash.

    Returns:
        A "<salt_hex>$<hash_hex>" string safe to store; never the plain text.
    """
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plain-text password against a stored hash.

    Args:
        password: The plain-text password supplied by the caller.
        password_hash: The stored "<salt_hex>$<hash_hex>" value.

    Returns:
        True if the password matches.
    """
    salt, _, expected = password_hash.partition("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return secrets.compare_digest(digest.hex(), expected)


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    """Verify credentials against the seeded user table.

    Args:
        session: An active async database session.
        username: The submitted username.
        password: The submitted plain-text password.

    Returns:
        The matching active User, or None if credentials are invalid.
    """
    user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_session(session: AsyncSession, user_id: str, *, now: datetime | None = None) -> str:
    """Issue a new opaque server-side session token for a user.

    Args:
        session: An active async database session.
        user_id: The id of the user to issue a session for.
        now: Issue time (injectable for tests); defaults to the current UTC time.

    Returns:
        The new session token, valid for SESSION_TTL_MINUTES from `now`.
    """
    issued_at = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            token=token,
            user_id=user_id,
            created_at=issued_at,
            expires_at=issued_at + timedelta(minutes=get_settings().session_ttl_minutes),
        )
    )
    await session.commit()
    return token


async def get_active_session_user(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> User | None:
    """Resolve a bearer token to its user, honoring expiry and immediate revocation.

    Args:
        session: An active async database session.
        token: The bearer token from the Authorization header.
        now: Evaluation time (injectable for tests); defaults to the current UTC time.

    Returns:
        The User if the token exists, is not revoked and has not expired, else None.
    """
    user_session = (
        await session.execute(select(UserSession).where(UserSession.token == token))
    ).scalar_one_or_none()
    if user_session is None or user_session.revoked_at is not None:
        return None
    if user_session.expires_at <= (now or datetime.now(timezone.utc)):
        return None
    return (await session.execute(select(User).where(User.id == user_session.user_id))).scalar_one_or_none()


async def revoke_session(session: AsyncSession, token: str) -> None:
    """Revoke a session immediately, without waiting for expiry.

    Args:
        session: An active async database session.
        token: The token to revoke.
    """
    user_session = (
        await session.execute(select(UserSession).where(UserSession.token == token))
    ).scalar_one_or_none()
    if user_session is not None:
        user_session.revoked_at = datetime.now(timezone.utc)
        await session.commit()
