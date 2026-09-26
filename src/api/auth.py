"""POST /api/v1/auth/login and /logout — mock LDAP/AD authentication and session end."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from src.db import async_session_factory
from src.deps.auth import get_current_user
from src.errors import ApiError
from src.models.auth import User
from src.services.auth_service import authenticate, create_session, revoke_session
from src.services.login_throttle import clear_username_failures, record_failure, seconds_until_unlocked

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Credentials submitted to the mock LDAP/AD login endpoint."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """The issued bearer session token."""

    token: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate a demo user and issue a server-side session token.

    Args:
        body: The submitted username/password.
        request: The current request; the submitted login (never the
            password) is attached for the audit journal.

    Returns:
        A LoginResponse carrying the new bearer token.

    Raises:
        HTTPException: 401 if the credentials are invalid.
    """
    request.state.audit["username"] = body.username
    ip = request.client.host if request.client else None
    async with async_session_factory() as session:
        # Блокировку проверяем до пароля: во время блокировки не пускает и верный пароль.
        retry_after = await seconds_until_unlocked(session, body.username, ip)
        if retry_after is not None:
            request.state.audit["details"] = {"reason": "locked_out"}
            raise ApiError(
                429,
                "TOO_MANY_REQUESTS",
                "Слишком много неудачных попыток входа, повторите позже",
                retryable=True,
                details={"retry_after_seconds": retry_after},
            )

        user = await authenticate(session, body.username, body.password)
        if user is None:
            await record_failure(session, body.username, ip)
            raise HTTPException(status_code=401, detail="invalid username or password")

        await clear_username_failures(session, body.username)
        request.state.audit["user_id"] = user.id
        token = await create_session(session, user.id)
    return LoginResponse(token=token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    user: User = Depends(get_current_user),
) -> None:
    """Revoke the caller's own session token immediately.

    Args:
        request: The current request; the actor is attached for the audit
            journal before revocation (afterwards the token no longer resolves).
        authorization: The raw bearer header of the session being closed.
        user: The authenticated caller (401 if the token is missing, expired or revoked).
    """
    request.state.audit["user_id"] = user.id
    request.state.audit["username"] = user.username
    token = (authorization or "").removeprefix("Bearer ").strip()
    async with async_session_factory() as session:
        await revoke_session(session, token)
