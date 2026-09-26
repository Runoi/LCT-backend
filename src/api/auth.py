"""POST /api/v1/auth/login — mock LDAP/AD authentication."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.db import async_session_factory
from src.services.auth_service import authenticate, create_session

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
    async with async_session_factory() as session:
        user = await authenticate(session, body.username, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid username or password")
        request.state.audit["user_id"] = user.id
        token = await create_session(session, user.id)
    return LoginResponse(token=token)
