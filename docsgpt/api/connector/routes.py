import base64
import html
import json
import uuid
from typing import Optional
from urllib.parse import urlencode, urlsplit


from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    request
)
from flask_restx import fields, Namespace, Resource


from docsgpt.api import api
from docsgpt.api.user.tasks import (
    ingest_connector_task,
)
from docsgpt.core.settings import settings
from docsgpt.parser.connectors.connector_creator import ConnectorCreator
from docsgpt.storage.db.repositories.connector_sessions import (
    ConnectorSessionsRepository,
    owns_connector_session,
)
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.session import db_readonly, db_session


connector = Blueprint("connector", __name__)
connectors_ns = Namespace("connectors", description="Connector operations", path="/")
api.add_namespace(connectors_ns)

# Fixed callback status path to prevent open redirect
CALLBACK_STATUS_PATH = "/api/connectors/callback-status"


def build_callback_redirect(params: dict) -> str:
    """Build a safe redirect URL to the callback status page.

    Uses a fixed path and properly URL-encodes all parameters
    to prevent URL injection and open redirect vulnerabilities.
    """
    return f"{CALLBACK_STATUS_PATH}?{urlencode(params)}"


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_DEV_FRONTEND_PORT = 5173


def _origin_of(url: Optional[str]) -> Optional[str]:
    """Normalized ``scheme://host[:port]`` origin of an http(s) URL, or None."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == {"http": 80, "https": 443}[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def connector_allowed_origins(request_host_url: str) -> list[str]:
    """Frontend origins the OAuth popup may hand a connector session token to."""
    candidates = [
        request_host_url,
        settings.CONNECTOR_REDIRECT_BASE_URI,
        settings.OIDC_FRONTEND_URL,
        *(settings.CONNECTOR_ALLOWED_ORIGINS or "").split(","),
    ]
    callback_origin = _origin_of(settings.CONNECTOR_REDIRECT_BASE_URI)
    if callback_origin:
        callback = urlsplit(callback_origin)
        if callback.hostname in _LOOPBACK_HOSTS:
            callback_port = f":{callback.port}" if callback.port else ""
            for host in ("localhost", "127.0.0.1"):
                candidates += [f"http://{host}:{_DEV_FRONTEND_PORT}", f"{callback.scheme}://{host}{callback_port}"]
    origins: list[str] = []
    for candidate in candidates:
        origin = _origin_of(candidate)
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def _js_literal(value) -> str:
    """Encode a value as a JavaScript literal that is safe inside an inline script."""
    return json.dumps(value).replace("</", "<\\/").replace("<!--", "<\\!--")


def _render_callback_page(
    status: str, message: str, provider_raw: str, session_token: str = "", user_email: str = "",
):
    """Popup page that reports an OAuth result to the opener on allowed origins only."""
    status = status if status in ("success", "error", "cancelled") else "error"
    # The script only carries server-side values: the provider key comes from the
    # supported-connector list rather than the request, and no request text is posted.
    provider_key = next(
        (key for key in ConnectorCreator.get_supported_connectors() if key == provider_raw.lower()), None,
    )
    payload = None
    if provider_key and status == "success" and session_token:
        payload = {"type": f"{provider_key}_auth_success", "session_token": session_token, "user_email": user_email}
    elif provider_key and status == "error":
        # The frontend shows its own localized failure message; cancellations are
        # reported when the popup closes.
        payload = {"type": f"{provider_key}_auth_error"}
    target_origins = connector_allowed_origins(request.host_url) if payload else []
    provider = html.escape(provider_raw.replace("_", " ").title())
    connected_as = (
        f"<p>Connected as: {html.escape(user_email)}</p>" if status == "success" and user_email else ""
    )
    closing_note = (
        f"Your {provider} is now connected and ready to use." if status == "success"
        else "Feel free to close this window."
    )
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{provider} Authentication</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 40px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .success {{ color: #4CAF50; }}
            .error {{ color: #F44336; }}
            .cancelled {{ color: #FF9800; }}
        </style>
        <script>
            window.onload = function() {{
                const payload = {_js_literal(payload)};
                const targetOrigins = {_js_literal(target_origins)};

                if (payload && window.opener) {{
                    targetOrigins.forEach(function(origin) {{
                        window.opener.postMessage(payload, origin);
                    }});
                }}
                setTimeout(() => window.close(), 3000);
            }};
        </script>
    </head>
    <body>
        <div class="container">
            <h2>{provider} Authentication</h2>
            <div class="{status}">
                <p>{html.escape(message)}</p>
                {connected_as}
            </div>
            <p><small>You can close this window. {closing_note}</small></p>
        </div>
    </body>
    </html>
    """
    return make_response(
        html_content,
        200,
        {"Content-Type": "text/html", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )



@connectors_ns.route("/api/connectors/auth")
class ConnectorAuth(Resource):
    @api.doc(description="Get connector OAuth authorization URL", params={"provider": "Connector provider (e.g., google_drive)"})
    def get(self):
        try:
            provider = request.args.get('provider') or request.args.get('source')
            if not provider:
                return make_response(jsonify({"success": False, "error": "Missing provider"}), 400)

            if not ConnectorCreator.is_supported(provider):
                return make_response(jsonify({"success": False, "error": f"Unsupported provider: {provider}"}), 400)

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user_id = decoded_token.get('sub')

            with db_session() as conn:
                session_row = ConnectorSessionsRepository(conn).upsert(
                    user_id, provider, status="pending",
                )
            session_pg_id = str(session_row["id"])
            state_dict = {
                "provider": provider,
                "object_id": session_pg_id,
            }
            state = base64.urlsafe_b64encode(json.dumps(state_dict).encode()).decode()

            auth = ConnectorCreator.create_auth(provider)
            authorization_url = auth.get_authorization_url(state=state)
            # The popup drops results for origins outside the allowlist, which the
            # user only sees as a cancelled sign-in; name the missing origin here.
            request_origin = _origin_of(request.headers.get("Origin"))
            if request_origin and request_origin not in connector_allowed_origins(request.host_url):
                current_app.logger.warning(
                    f"Connector sign-in requested from {request_origin}, which cannot receive the result; "
                    "add it to CONNECTOR_ALLOWED_ORIGINS"
                )
            return make_response(jsonify({
                "success": True,
                "authorization_url": authorization_url,
                "state": state,
                "callback_origin": _origin_of(settings.CONNECTOR_REDIRECT_BASE_URI),
            }), 200)
        except Exception as e:
            current_app.logger.error(f"Error generating connector auth URL: {e}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to generate authorization URL"}), 500)


@connectors_ns.route("/api/connectors/callback")
class ConnectorsCallback(Resource):
    @api.doc(description="Handle OAuth callback for external connectors")
    def get(self):
        """Handle OAuth callback for external connectors"""
        try:
            from docsgpt.parser.connectors.connector_creator import ConnectorCreator
            from flask import request, redirect

            authorization_code = request.args.get('code')
            state = request.args.get('state')
            error = request.args.get('error')

            state_dict = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            provider = state_dict.get("provider")
            state_object_id = state_dict.get("object_id")

            # Validate provider
            if not provider or not isinstance(provider, str) or not ConnectorCreator.is_supported(provider):
                return redirect(build_callback_redirect({
                    "status": "error",
                    "message": "Invalid provider"
                }))

            if error:
                if error == "access_denied":
                    return redirect(build_callback_redirect({
                        "status": "cancelled",
                        "message": "Authentication was cancelled. You can try again if you'd like to connect your account.",
                        "provider": provider
                    }))
                else:
                    current_app.logger.warning(f"OAuth error in callback: {error}")
                    return redirect(build_callback_redirect({
                        "status": "error",
                        "message": "Authentication failed. Please try again and make sure to grant all requested permissions.",
                        "provider": provider
                    }))

            if not authorization_code:
                return redirect(build_callback_redirect({
                    "status": "error",
                    "message": "Authentication failed. Please try again and make sure to grant all requested permissions.",
                    "provider": provider
                }))

            try:
                auth = ConnectorCreator.create_auth(provider)
                token_info = auth.exchange_code_for_tokens(authorization_code)

                session_token = str(uuid.uuid4())

                try:
                    if provider == "google_drive":
                        credentials = auth.create_credentials_from_token_info(token_info)
                        service = auth.build_drive_service(credentials)
                        user_info = service.about().get(fields="user").execute()
                        user_email = user_info.get('user', {}).get('emailAddress', 'Connected User')
                    else:
                        user_email = token_info.get('user_info', {}).get('email', 'Connected User')

                except Exception as e:
                    current_app.logger.warning(f"Could not get user info: {e}")
                    user_email = 'Connected User'

                sanitized_token_info = auth.sanitize_token_info(token_info)

                # ``object_id`` in the OAuth state is the PG session row
                # UUID (new flow) or a legacy Mongo ObjectId (pre-cutover
                # issued state). Try UUID update first; fall back to
                # legacy id path.
                patch = {
                    "session_token": session_token,
                    "token_info": sanitized_token_info,
                    "user_email": user_email,
                    "status": "authorized",
                }
                with db_session() as conn:
                    repo = ConnectorSessionsRepository(conn)
                    if state_object_id:
                        value = str(state_object_id)
                        updated = False
                        if len(value) == 36 and "-" in value:
                            updated = repo.update(value, patch)
                        if not updated:
                            repo.update_by_legacy_id(value, patch)

                # Render instead of redirecting so the session token never
                # lands in a URL (browser history, access logs, Referer).
                return _render_callback_page(
                    "success", "Authentication successful", provider,
                    session_token=session_token, user_email=user_email,
                )

            except Exception as e:
                current_app.logger.error(f"Error exchanging code for tokens: {str(e)}", exc_info=True)
                return redirect(build_callback_redirect({
                    "status": "error",
                    "message": "Authentication failed. Please try again and make sure to grant all requested permissions.",
                    "provider": provider
                }))

        except Exception as e:
            current_app.logger.error(f"Error handling connector callback: {e}")
            return redirect(build_callback_redirect({
                "status": "error",
                "message": "Authentication failed. Please try again and make sure to grant all requested permissions."
            }))


@connectors_ns.route("/api/connectors/files")
class ConnectorFiles(Resource):
    @api.expect(api.model("ConnectorFilesModel", {
        "provider": fields.String(required=True),
        "session_token": fields.String(required=True),
        "folder_id": fields.String(required=False),
        "limit": fields.Integer(required=False),
        "page_token": fields.String(required=False),
        "search_query": fields.String(required=False),
    }))
    @api.doc(description="List files from a connector provider (supports pagination and search)")
    def post(self):
        try:
            data = request.get_json()
            provider = data.get('provider')
            session_token = data.get('session_token')
            limit = data.get('limit', 10)

            if not provider or not session_token:
                return make_response(jsonify({"success": False, "error": "provider and session_token are required"}), 400)

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user = decoded_token.get('sub')
            with db_readonly() as conn:
                session = ConnectorSessionsRepository(conn).get_by_session_token(
                    session_token,
                )
            if not owns_connector_session(session, user, provider):
                return make_response(jsonify({"success": False, "error": "Invalid or unauthorized session"}), 401)

            loader = ConnectorCreator.create_connector(provider, session_token)

            generic_keys = {'provider', 'session_token'}
            input_config = {
                k: v for k, v in data.items() if k not in generic_keys
            }
            input_config['list_only'] = True
                
            documents = loader.load_data(input_config)

            files = []
            for doc in documents[:limit]:
                metadata = doc.extra_info
                modified_time = metadata.get('modified_time')
                if modified_time:
                    date_part = modified_time.split('T')[0]
                    time_part = modified_time.split('T')[1].split('.')[0].split('Z')[0]
                    formatted_time = f"{date_part} {time_part}"
                else:
                    formatted_time = None

                files.append({
                    'id': doc.doc_id,
                    'name': metadata.get('file_name', 'Unknown File'),
                    'type': metadata.get('mime_type', 'unknown'),
                    'size': metadata.get('size', None),
                    'modifiedTime': formatted_time,
                    'isFolder': metadata.get('is_folder', False)
                })

            next_token = getattr(loader, 'next_page_token', None)
            has_more = bool(next_token)

            return make_response(jsonify({
                "success": True, 
                "files": files, 
                "total": len(files), 
                "next_page_token": next_token, 
                "has_more": has_more
            }), 200)
        except Exception as e:
            current_app.logger.error(f"Error loading connector files: {e}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load files"}), 500)


@connectors_ns.route("/api/connectors/validate-session")
class ConnectorValidateSession(Resource):
    @api.expect(api.model("ConnectorValidateSessionModel", {"provider": fields.String(required=True), "session_token": fields.String(required=True)}))
    @api.doc(description="Validate connector session token and return user info and access token")
    def post(self):
        try:
            data = request.get_json()
            provider = data.get('provider')
            session_token = data.get('session_token')
            if not provider or not session_token:
                return make_response(jsonify({"success": False, "error": "provider and session_token are required"}), 400)

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user = decoded_token.get('sub')

            with db_readonly() as conn:
                session = ConnectorSessionsRepository(conn).get_by_session_token(
                    session_token,
                )
            if not owns_connector_session(session, user, provider) or not session.get("token_info"):
                return make_response(jsonify({"success": False, "error": "Invalid or expired session"}), 401)

            token_info = session["token_info"]
            auth = ConnectorCreator.create_auth(provider)
            is_expired = auth.is_token_expired(token_info)

            if is_expired and token_info.get('refresh_token'):
                try:
                    refreshed_token_info = auth.refresh_access_token(token_info.get('refresh_token'))
                    sanitized_token_info = auth.sanitize_token_info(refreshed_token_info)
                    with db_session() as conn:
                        repo = ConnectorSessionsRepository(conn)
                        row = repo.get_by_session_token(session_token)
                        if row:
                            repo.update(str(row["id"]), {"token_info": sanitized_token_info})
                    token_info = sanitized_token_info
                    is_expired = False
                except Exception as refresh_error:
                    current_app.logger.error(f"Failed to refresh token: {refresh_error}")
            
            if is_expired:
                return make_response(jsonify({
                    "success": False,
                    "expired": True,
                    "error": "Session token has expired. Please reconnect."
                }), 401)

            _base_fields = {"access_token", "refresh_token", "token_uri", "expiry"}
            provider_extras = {k: v for k, v in token_info.items() if k not in _base_fields}

            response_data = {
                "success": True,
                "expired": False,
                "user_email": session.get('user_email', 'Connected User'),
                "access_token": token_info.get('access_token'),
                **provider_extras,
            }

            return make_response(jsonify(response_data), 200)
        except Exception as e:
            current_app.logger.error(f"Error validating connector session: {e}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to validate session"}), 500)


@connectors_ns.route("/api/connectors/disconnect")
class ConnectorDisconnect(Resource):
    @api.expect(api.model("ConnectorDisconnectModel", {"provider": fields.String(required=True), "session_token": fields.String(required=False)}))
    @api.doc(description="Disconnect a connector session")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
        try:
            data = request.get_json()
            provider = data.get('provider')
            session_token = data.get('session_token')
            if not provider:
                return make_response(jsonify({"success": False, "error": "provider is required"}), 400)

            if session_token:
                with db_session() as conn:
                    ConnectorSessionsRepository(conn).delete_by_session_token(
                        session_token, decoded_token.get('sub'),
                    )

            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            current_app.logger.error(f"Error disconnecting connector session: {e}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to disconnect session"}), 500)


@connectors_ns.route("/api/connectors/sync")
class ConnectorSync(Resource):
    @api.expect(
        api.model(
            "ConnectorSyncModel",
            {
                "source_id": fields.String(required=True, description="Source ID to sync"),
                "session_token": fields.String(required=True, description="Authentication token")
            },
        )
    )
    @api.doc(description="Sync connector source to check for modifications")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)

        try:
            data = request.get_json()
            source_id = data.get('source_id')
            session_token = data.get('session_token')

            if not all([source_id, session_token]):
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "source_id and session_token are required"
                    }), 
                    400
                )
            user_id = decoded_token.get('sub')
            with db_readonly() as conn:
                source = SourcesRepository(conn).get_any(source_id, user_id)
            if not source:
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "Source not found"
                    }),
                    404
                )

            # ``get_any`` already scopes by ``user_id``; an extra guard
            # here would be dead code.

            remote_data = source.get('remote_data') or {}
            if isinstance(remote_data, str):
                try:
                    remote_data = json.loads(remote_data)
                except json.JSONDecodeError:
                    current_app.logger.error(f"Invalid remote_data format for source {source_id}")
                    remote_data = {}

            source_type = remote_data.get('provider')
            if not source_type:
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "Source provider not found in remote_data"
                    }), 
                    400
                )

            with db_readonly() as conn:
                session = ConnectorSessionsRepository(conn).get_by_session_token(session_token)
            if not owns_connector_session(session, user_id, source_type):
                return make_response(
                    jsonify({"success": False, "error": "Invalid or unauthorized session"}),
                    401,
                )

            # Extract configuration from remote_data
            file_ids = remote_data.get('file_ids', [])
            folder_ids = remote_data.get('folder_ids', [])
            recursive = remote_data.get('recursive', True)

            # Start the sync task
            task = ingest_connector_task.delay(
                job_name=source.get('name'),
                user=decoded_token.get('sub'),
                source_type=source_type,
                session_token=session_token,
                file_ids=file_ids,
                folder_ids=folder_ids,
                recursive=recursive,
                retriever=source.get('retriever', 'classic'),
                operation_mode="sync",
                doc_id=str(source.get('id') or source_id),
                sync_frequency=source.get('sync_frequency', 'never')
            )

            return make_response(
                jsonify({
                    "success": True,
                    "task_id": task.id
                }), 
                200
            )

        except Exception as err:
            current_app.logger.error(
                f"Error syncing connector source: {err}",
                exc_info=True
            )
            return make_response(
                jsonify({
                    "success": False,
                    "error": "Failed to sync connector source"
                }),
                400
            )


@connectors_ns.route("/api/connectors/callback-status")
class ConnectorCallbackStatus(Resource):
    @api.doc(description="Return HTML page with connector authentication status")
    def get(self):
        """Return HTML page with connector authentication status"""
        try:
            # Query params are attacker-controllable, so this page never
            # carries a session token; the OAuth callback renders that itself.
            return _render_callback_page(
                request.args.get('status', 'error'),
                request.args.get('message', ''),
                request.args.get('provider', 'connector'),
            )
        except Exception as e:
            current_app.logger.error(f"Error rendering callback status page: {e}")
            return make_response("Authentication error occurred", 500, {'Content-Type': 'text/html'})


