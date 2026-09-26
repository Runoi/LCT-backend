"""Structured API errors: {"error": {code, message, trace_id, details, retryable}}.

See `BACKEND_REQUIREMENTS_FROM_FRONTEND_TZ.md` section 9 for the contract.
"""
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_STATUS_FALLBACK_CODES = {
    400: "VALIDATION_ERROR",
    401: "SESSION_EXPIRED",
    403: "ACCESS_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "DOMAIN_VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    503: "SOURCE_UNAVAILABLE",
}


class ApiError(Exception):
    """A structured, client-facing API error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


def _trace_id(request: Request) -> str:
    # Тот же trace_id, что в заголовке X-Trace-Id и в журнале аудита.
    return getattr(request.state, "trace_id", None) or f"tr_{uuid.uuid4().hex[:20]}"


def _error_body(code: str, message: str, retryable: bool, details: dict, trace_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "trace_id": trace_id,
            "details": details,
            "retryable": retryable,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers so every error response uses the documented envelope.

    Args:
        app: The FastAPI application to attach handlers to.
    """

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.retryable, exc.details, _trace_id(request)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_FALLBACK_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code, content=_error_body(code, message, False, {}, _trace_id(request))
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=_error_body(
                "VALIDATION_ERROR", "Ошибка валидации запроса", False, {"errors": exc.errors()}, _trace_id(request)
            ),
        )
