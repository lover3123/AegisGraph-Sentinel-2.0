"""Structured API error response builders."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from .base_exceptions import AegisException
from .error_codes import ErrorCode


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_error_payload(
    *,
    code: Union[ErrorCode, str],
    type_name: str,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the standardized nested error response body."""
    code_value = code.value if isinstance(code, ErrorCode) else str(code)
    payload: Dict[str, Any] = {
        "error": {
            "code": code_value,
            "type": type_name,
            "message": message,
            "request_id": request_id,
            "timestamp": timestamp or utc_timestamp(),
            "details": details or {},
        }
    }
    return payload


def build_error_from_aegis_exception(
    exc: AegisException,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    return build_error_payload(
        code=exc.code,
        type_name=exc.type_name,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )
