"""Administrative authentication and authorization module for Qmoosa Equality.

Security & Architectural Disclosures:
1. Role Identity vs Individual Identity:
   A single shared administrative API key identifies a service/operator role (e.g. 'council_operator');
   it does NOT establish verifiable individual identity across multiple human reviewers.
   For multi-operator governance, individual hardware-key signing or multisig must be used.
2. Ingress & Transport Security:
   Administrative endpoints MUST be terminated with TLS/HTTPS at the edge reverse proxy.
   When running behind a trusted reverse proxy (e.g. Nginx, Cloudflare, Traefik), ensure
   X-Forwarded-Proto is validated and plain HTTP administrative traffic is rejected.
"""
import hmac
import os
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)


def get_admin_api_key() -> Optional[str]:
    """Retrieve and sanitize ADMIN_API_KEY from environment."""
    key = os.getenv("ADMIN_API_KEY")
    if key is not None:
        key = key.strip()
        if not key:
            return None
    return key


def get_admin_operator_identity() -> str:
    """Retrieve server-side verified operator identity, default to 'verified_council_lead'."""
    identity = os.getenv("ADMIN_OPERATOR_IDENTITY", "verified_council_lead").strip()
    return identity or "verified_council_lead"


def get_authenticated_admin(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Enforce strict administrative authorization for governance actions.

    Rules:
    1. If ADMIN_API_KEY is missing, empty, or whitespace-only, fails closed with HTTP 503.
    2. Missing or invalid credentials return HTTP 401.
    3. Token comparison is performed in constant time (hmac.compare_digest).
    4. Reviewer identity is derived strictly from server-side configuration (ADMIN_OPERATOR_IDENTITY).
    5. Caller-supplied identity headers (e.g. 'x-admin-identity') and request-body identity fields are ignored.
    6. Raw tokens and Authorization headers are NEVER logged.
    """
    configured_key = get_admin_api_key()
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrative operations disabled: ADMIN_API_KEY is not configured or is whitespace-only.",
        )

    token = None
    if creds and creds.credentials:
        token = creds.credentials.strip()
    elif "x-admin-key" in request.headers:
        token = request.headers["x-admin-key"].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Administrative Bearer token or X-Admin-Key header required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison to prevent timing side-channel attacks
    if not hmac.compare_digest(token.encode("utf-8"), configured_key.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid administrative credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Actor identity derived strictly from server configuration
    return get_admin_operator_identity()
