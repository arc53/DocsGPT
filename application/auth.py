"""Authentication middleware for DocsGPT.

Supports multiple authentication types including simple JWT, session JWT,
and Authentik OIDC authentication.
"""

from typing import Dict, Optional
from jose import jwt

from application.core.settings import settings


def handle_auth(request, data: Optional[Dict] = None) -> Optional[Dict]:
    """Handle authentication based on configured AUTH_TYPE.
    
    Args:
        request: Flask request object.
        data: Optional additional data for authentication.
        
    Returns:
        User information dictionary if authenticated, None if not required,
        or error dictionary if authentication fails.
    """
    if data is None:
        data = {}
        
    if settings.AUTH_TYPE in ["simple_jwt", "session_jwt"]:
        return _handle_jwt_auth(request)
    elif settings.AUTH_TYPE == "authentik":
        return _handle_authentik_auth(request)
    else:
        # No authentication required
        return {"sub": "local"}


def _handle_jwt_auth(request) -> Optional[Dict]:
    """Handle simple JWT or session JWT authentication.
    
    Args:
        request: Flask request object.
        
    Returns:
        Decoded JWT claims or error dictionary.
    """
    jwt_token = request.headers.get("Authorization")
    if not jwt_token:
        return None

    jwt_token = jwt_token.replace("Bearer ", "")

    try:
        decoded_token = jwt.decode(
            jwt_token,
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        return decoded_token
    except Exception as e:
        return {
            "message": f"Authentication error: {str(e)}",
            "error": "invalid_token",
        }


def _handle_authentik_auth(request) -> Optional[Dict]:
    """Handle Authentik OIDC authentication.
    
    Args:
        request: Flask request object.
        
    Returns:
        User information from validated ID token or error dictionary.
    """
    try:
        from application.auth.authentik import get_authentik_service, AuthentikOIDCError
    except ImportError:
        return {
            "message": "Authentik authentication not available - missing dependencies",
            "error": "authentik_unavailable",
        }
        
    # Get ID token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
        
    if not auth_header.startswith("Bearer "):
        return {
            "message": "Invalid authorization header format",
            "error": "invalid_auth_header",
        }
        
    id_token = auth_header.replace("Bearer ", "")
    
    try:
        authentik_service = get_authentik_service()
        
        # Validate ID token and extract user claims
        user_claims = authentik_service.validate_id_token(id_token)
        
        # Return user information compatible with existing auth flow
        return {
            "sub": user_claims.get("sub"),
            "email": user_claims.get("email"),
            "name": user_claims.get("name", user_claims.get("preferred_username")),
            "groups": user_claims.get("groups", []),
            "authentik_claims": user_claims,
        }
        
    except AuthentikOIDCError as e:
        return {
            "message": f"Authentik authentication error: {str(e)}",
            "error": "authentik_auth_failed",
        }
    except Exception as e:
        return {
            "message": f"Authentication error: {str(e)}",
            "error": "auth_system_error",
        }
