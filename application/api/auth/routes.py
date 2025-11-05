"""Authentik OIDC authentication API routes.

Provides REST endpoints for Authentik OIDC authentication flow including
login initiation, OAuth2 callback handling, logout, and user info retrieval.
"""

from flask import Blueprint, request, jsonify, session, redirect
from typing import Dict, Any, Optional
import logging

from application.core.settings import settings

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _get_authentik_service():
    """Get Authentik service instance with error handling.
    
    Returns:
        AuthentikOIDCService instance or None if not available.
    """
    try:
        from application.auth.authentik import get_authentik_service
        return get_authentik_service()
    except ImportError as e:
        logger.error(f"Authentik service not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Authentik service: {e}")
        return None


@auth_bp.route("/authentik/login", methods=["GET"])
def authentik_login():
    """Initiate Authentik OIDC authentication flow.
    
    Returns:
        JSON response with authorization URL and state.
    """
    if settings.AUTH_TYPE != "authentik":
        return jsonify({
            "error": "authentik_not_enabled",
            "message": "Authentik authentication is not enabled"
        }), 400
        
    authentik_service = _get_authentik_service()
    if not authentik_service:
        return jsonify({
            "error": "authentik_unavailable",
            "message": "Authentik service is not available"
        }), 500
        
    try:
        # Generate authorization URL with state for CSRF protection
        auth_url, state = authentik_service.generate_auth_url()
        
        # Store state in session for validation
        session["authentik_state"] = state
        
        return jsonify({
            "auth_url": auth_url,
            "state": state
        })
        
    except Exception as e:
        logger.error(f"Failed to generate authorization URL: {e}")
        return jsonify({
            "error": "auth_generation_failed",
            "message": "Failed to generate authorization URL"
        }), 500


@auth_bp.route("/authentik/callback", methods=["GET", "POST"])
def authentik_callback():
    """Handle OAuth2 callback from Authentik.
    
    Returns:
        JSON response with tokens and user information.
    """
    if settings.AUTH_TYPE != "authentik":
        return jsonify({
            "error": "authentik_not_enabled",
            "message": "Authentik authentication is not enabled"
        }), 400
        
    authentik_service = _get_authentik_service()
    if not authentik_service:
        return jsonify({
            "error": "authentik_unavailable",
            "message": "Authentik service is not available"
        }), 500
    
    # Get parameters from request
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    
    # Handle OAuth error responses
    if error:
        error_description = request.args.get("error_description", "Unknown error")
        logger.warning(f"OAuth error: {error} - {error_description}")
        return jsonify({
            "error": f"oauth_{error}",
            "message": error_description
        }), 400
    
    # Validate required parameters
    if not code:
        return jsonify({
            "error": "missing_code",
            "message": "Authorization code is required"
        }), 400
        
    if not state:
        return jsonify({
            "error": "missing_state",
            "message": "State parameter is required"
        }), 400
    
    # Validate state for CSRF protection
    stored_state = session.get("authentik_state")
    if not stored_state or stored_state != state:
        return jsonify({
            "error": "invalid_state",
            "message": "Invalid state parameter"
        }), 400
    
    try:
        # Exchange code for tokens
        token_response = authentik_service.exchange_code_for_tokens(code)
        
        id_token = token_response.get("id_token")
        access_token = token_response.get("access_token")
        
        if not id_token:
            return jsonify({
                "error": "missing_id_token",
                "message": "ID token not received from Authentik"
            }), 500
        
        # Validate ID token and extract user claims
        user_claims = authentik_service.validate_id_token(id_token)
        
        # Get additional user info if access token is available
        user_info = {}
        if access_token:
            try:
                user_info = authentik_service.get_user_info(access_token)
            except Exception as e:
                logger.warning(f"Failed to get user info: {e}")
        
        # Clean up session
        session.pop("authentik_state", None)
        
        # Return tokens and user information
        response_data = {
            "id_token": id_token,
            "access_token": access_token,
            "user": {
                "sub": user_claims.get("sub"),
                "email": user_claims.get("email"),
                "name": user_claims.get("name", user_claims.get("preferred_username")),
                "groups": user_claims.get("groups", []),
            },
            "expires_in": token_response.get("expires_in"),
            "token_type": token_response.get("token_type", "Bearer")
        }
        
        # Add user info if available
        if user_info:
            response_data["user_info"] = user_info
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Authentication callback failed: {e}")
        session.pop("authentik_state", None)  # Clean up on error
        return jsonify({
            "error": "callback_processing_failed",
            "message": "Failed to process authentication callback"
        }), 500


@auth_bp.route("/authentik/userinfo", methods=["GET"])
def authentik_userinfo():
    """Get current user information using access token.
    
    Returns:
        JSON response with user information.
    """
    if settings.AUTH_TYPE != "authentik":
        return jsonify({
            "error": "authentik_not_enabled",
            "message": "Authentik authentication is not enabled"
        }), 400
        
    authentik_service = _get_authentik_service()
    if not authentik_service:
        return jsonify({
            "error": "authentik_unavailable",
            "message": "Authentik service is not available"
        }), 500
    
    # Get access token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({
            "error": "missing_token",
            "message": "Access token is required"
        }), 401
    
    access_token = auth_header.replace("Bearer ", "")
    
    try:
        user_info = authentik_service.get_user_info(access_token)
        return jsonify(user_info)
        
    except Exception as e:
        logger.error(f"Failed to get user info: {e}")
        return jsonify({
            "error": "userinfo_failed",
            "message": "Failed to retrieve user information"
        }), 500


@auth_bp.route("/authentik/logout", methods=["POST"])
def authentik_logout():
    """Handle logout and token revocation.
    
    Returns:
        JSON response confirming logout.
    """
    if settings.AUTH_TYPE != "authentik":
        return jsonify({
            "error": "authentik_not_enabled",
            "message": "Authentik authentication is not enabled"
        }), 400
        
    authentik_service = _get_authentik_service()
    if not authentik_service:
        return jsonify({
            "error": "authentik_unavailable",
            "message": "Authentik service is not available"
        }), 500
    
    # Get tokens from request body or headers
    data = request.get_json() or {}
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    
    # Try to get access token from Authorization header if not in body
    if not access_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header.replace("Bearer ", "")
    
    revocation_results = []
    
    # Revoke access token
    if access_token:
        try:
            success = authentik_service.revoke_token(access_token, "access_token")
            revocation_results.append({
                "token_type": "access_token",
                "revoked": success
            })
        except Exception as e:
            logger.warning(f"Failed to revoke access token: {e}")
            revocation_results.append({
                "token_type": "access_token",
                "revoked": False,
                "error": str(e)
            })
    
    # Revoke refresh token
    if refresh_token:
        try:
            success = authentik_service.revoke_token(refresh_token, "refresh_token")
            revocation_results.append({
                "token_type": "refresh_token",
                "revoked": success
            })
        except Exception as e:
            logger.warning(f"Failed to revoke refresh token: {e}")
            revocation_results.append({
                "token_type": "refresh_token",
                "revoked": False,
                "error": str(e)
            })
    
    # Clear session
    session.clear()
    
    return jsonify({
        "message": "Logout completed",
        "revocation_results": revocation_results
    })


@auth_bp.route("/status", methods=["GET"])
def auth_status():
    """Get authentication status and configuration.
    
    Returns:
        JSON response with authentication status.
    """
    response = {
        "auth_type": settings.AUTH_TYPE,
        "authentik_enabled": settings.AUTH_TYPE == "authentik",
        "requires_auth": settings.AUTH_TYPE in ["simple_jwt", "session_jwt", "authentik"],
    }
    
    if settings.AUTH_TYPE == "authentik":
        authentik_service = _get_authentik_service()
        response["authentik_available"] = authentik_service is not None
        
        if authentik_service:
            try:
                # Test OIDC discovery endpoint availability
                discovery = authentik_service.get_oidc_discovery()
                response["authentik_issuer"] = discovery.get("issuer")
                response["authentik_endpoints_available"] = True
            except Exception as e:
                logger.warning(f"Authentik endpoints not available: {e}")
                response["authentik_endpoints_available"] = False
                response["authentik_error"] = str(e)
    
    return jsonify(response)


# Blueprint registration function
def register_auth_routes(app):
    """Register authentication routes with Flask app.
    
    Args:
        app: Flask application instance.
    """
    app.register_blueprint(auth_bp)
