import base64
import html
import json
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
from docsgpt.api.user.resource_access import AccessDenied
from docsgpt.api.user.sources.access import load_source
from docsgpt.api.user.tasks import (
    ingest_connector_task,
)
from docsgpt.connectors import service
from docsgpt.core.settings import settings
from docsgpt.parser.connectors.connector_creator import ConnectorCreator
from docsgpt.storage.db.repositories.connector_sessions import (
    ConnectorSessionsRepository,
    owns_connector_session,
)
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
    connection_id: str = "",
):
    """Popup page that reports an OAuth result to the opener on allowed origins only."""
    status = status if status in ("success", "error", "cancelled") else "error"
    # The script only carries server-side values: the provider key comes from the
    # supported-connector list rather than the request, and no request text is posted.
    provider_key = next(
        (key for key in ConnectorCreator.get_auth_providers() if key == provider_raw.lower()), None,
    )
    payload = None
    if provider_key and status == "success" and session_token:
        payload = {
            "type": f"{provider_key}_auth_success",
            # The connection id is what current frontends use; the session
            # token is kept for one release for frontends from before it.
            "connection_id": connection_id,
            "session_token": session_token,
            "user_email": user_email,
        }
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



def build_authorization(
    provider: str, user_id: str, connection_id: Optional[str] = None, *, install: bool = False,
) -> dict:
    """Start an OAuth sign-in for ``provider`` and return its authorization URL.

    Args:
        provider: The connector, e.g. ``google_drive`` or ``github``.
        user_id: The caller.
        connection_id: The caller's connection to sign in again, if any.
        install: GitHub: send the user to install the GitHub App (where the
            repositories it can read are chosen) instead of straight to
            authorization. GitHub returns to the callback with the same
            state when the app requests authorization during installation.

    Raises:
        service.EncryptionKeyNotConfigured: See ``ensure_can_store_credentials``.
        service.ConnectionUnavailable: ``connection_id`` is not the caller's.
        ValueError: ``install`` for a provider with no installation page.
    """
    service.ensure_can_store_credentials()
    with db_session() as conn:
        session_row = service.begin_oauth(conn, user_id, provider, connection_id)
    state = base64.urlsafe_b64encode(
        json.dumps({"provider": provider, "object_id": str(session_row["id"])}).encode()
    ).decode()
    auth = ConnectorCreator.create_auth(provider)
    if install and not hasattr(auth, "get_installation_url"):
        raise ValueError(f"{provider} has no installation page")
    url = auth.get_installation_url(state=state) if install else auth.get_authorization_url(state=state)
    return {
        "authorization_url": url,
        "state": state,
        "callback_origin": _origin_of(settings.CONNECTOR_REDIRECT_BASE_URI),
    }


@connectors_ns.route("/api/connectors/auth")
class ConnectorAuth(Resource):
    @api.doc(description="Get connector OAuth authorization URL", params={"provider": "Connector provider (e.g., google_drive)"})
    def get(self):
        try:
            provider = request.args.get('provider') or request.args.get('source')
            if not provider:
                return make_response(jsonify({"success": False, "error": "Missing provider"}), 400)

            if not (ConnectorCreator.is_supported(provider) or ConnectorCreator.has_auth(provider)):
                return make_response(jsonify({"success": False, "error": f"Unsupported provider: {provider}"}), 400)

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user_id = decoded_token.get('sub')
            try:
                started = build_authorization(
                    provider, user_id, request.args.get("connection_id") or None,
                    install=request.args.get("install") in ("1", "true"),
                )
            except service.EncryptionKeyNotConfigured as err:
                return make_response(
                    jsonify({"success": False, "error": str(err), "code": "encryption_key_default"}), 400,
                )
            except service.ConnectionUnavailable:
                return make_response(jsonify({"success": False, "error": "Connection not found"}), 404)
            except service.ConnectorDisabled as err:
                return make_response(jsonify({"success": False, "error": str(err), "code": "disabled"}), 403)
            # The popup drops results for origins outside the allowlist, which the
            # user only sees as a cancelled sign-in; name the missing origin here.
            request_origin = _origin_of(request.headers.get("Origin"))
            if request_origin and request_origin not in connector_allowed_origins(request.host_url):
                current_app.logger.warning(
                    f"Connector sign-in requested from {request_origin}, which cannot receive the result; "
                    "add it to CONNECTOR_ALLOWED_ORIGINS"
                )
            return make_response(jsonify({"success": True, **started}), 200)
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

            if not state and request.args.get('installation_id'):
                # The GitHub App was installed from GitHub itself, not from a
                # DocsGPT sign-in: there is no state to tie the code to a user,
                # so the code is ignored and the user goes back to DocsGPT.
                return _render_callback_page(
                    "success",
                    "The GitHub App is installed. Return to DocsGPT and refresh the repository list.",
                    "github",
                )

            state_dict = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            provider = state_dict.get("provider")
            state_object_id = state_dict.get("object_id")

            # Validate provider
            if not provider or not isinstance(provider, str) or not (
                ConnectorCreator.is_supported(provider) or ConnectorCreator.has_auth(provider)
            ):
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

                try:
                    if provider == "google_drive":
                        credentials = auth.create_credentials_from_token_info(token_info)
                        drive_service = auth.build_drive_service(credentials)
                        user_info = drive_service.about().get(fields="user").execute()
                        user_email = user_info.get('user', {}).get('emailAddress', 'Connected User')
                    else:
                        # GitHub names the account by its login, the others by email.
                        user_info = token_info.get('user_info') or {}
                        user_email = user_info.get('email') or user_info.get('login') or 'Connected User'

                except Exception as e:
                    current_app.logger.warning(f"Could not get user info: {e}")
                    user_email = 'Connected User'

                sanitized_token_info = auth.sanitize_token_info(token_info)

                # ``object_id`` in the OAuth state is the PG session row
                # UUID (new flow) or a legacy Mongo ObjectId (pre-cutover
                # issued state).
                with db_session() as conn:
                    repo = ConnectorSessionsRepository(conn)
                    value = str(state_object_id or "")
                    state_row = repo.get(value) or (repo.get_by_legacy_id(value) if value else None)
                    if state_row is None or state_row.get("provider") != provider:
                        raise ValueError("OAuth state names no pending connection")
                    connection = service.complete_oauth(
                        conn, state_row, provider, sanitized_token_info, user_email,
                    )

                # Render instead of redirecting so the session token never
                # lands in a URL (browser history, access logs, Referer).
                return _render_callback_page(
                    "success", "Authentication successful", provider,
                    session_token=connection.get("session_token") or "", user_email=user_email,
                    connection_id=str(connection["id"]),
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
        "connection_id": fields.String(required=False),
        "session_token": fields.String(required=False, description="Legacy; use connection_id"),
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
            limit = data.get('limit', 10)

            if not provider or not (data.get('connection_id') or data.get('session_token')):
                return make_response(
                    jsonify({"success": False, "error": "provider and connection_id are required"}), 400,
                )

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user = decoded_token.get('sub')
            session = service.resolve_request_connection(user, provider, data)
            if session is None:
                return make_response(jsonify({"success": False, "error": "Invalid or unauthorized session"}), 401)

            try:
                loader = ConnectorCreator.create_connector(provider, connection_id=str(session["id"]))
            except service.ConnectionUnavailable:
                return make_response(
                    jsonify({"success": False, "error": "Reconnect to continue", "reconnect": True}), 401,
                )

            generic_keys = {'provider', 'session_token', 'connection_id'}
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
    @api.expect(api.model("ConnectorValidateSessionModel", {
        "provider": fields.String(required=True),
        "connection_id": fields.String(required=False),
        "session_token": fields.String(required=False, description="Legacy; use connection_id"),
    }))
    @api.doc(description="Validate a connection and return the account and a short-lived access token")
    def post(self):
        try:
            data = request.get_json() or {}
            provider = data.get('provider')
            if not provider or not (data.get('connection_id') or data.get('session_token')):
                return make_response(
                    jsonify({"success": False, "error": "provider and connection_id are required"}), 400,
                )

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user = decoded_token.get('sub')

            session = service.resolve_request_connection(user, provider, data)
            if session is None:
                return make_response(jsonify({"success": False, "error": "Invalid or expired session"}), 401)
            try:
                token = service.picker_token(str(session["id"]))
            except service.ConnectionUnavailable:
                return make_response(jsonify({
                    "success": False,
                    "expired": True,
                    "error": "Session token has expired. Please reconnect."
                }), 401)
            except service.TransientConnectionError:
                return make_response(
                    jsonify({"success": False, "error": "The provider is not responding. Try again."}), 503,
                )

            return make_response(jsonify({
                "success": True,
                "expired": False,
                "connection_id": str(session["id"]),
                "user_email": session.get('account_label') or session.get('user_email') or 'Connected User',
                **token,
            }), 200)
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
            if not provider:
                return make_response(jsonify({"success": False, "error": "provider is required"}), 400)

            session = service.resolve_request_connection(decoded_token.get('sub'), provider, data)
            if session is not None:
                with db_session() as conn:
                    service.disconnect(conn, session)

            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            current_app.logger.error(f"Error disconnecting connector session: {e}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to disconnect session"}), 500)


def _owner_connector_session(
    conn, owner_id: str, provider: str, connection_id: Optional[str] = None,
) -> Optional[dict]:
    """The owner's usable connection for ``provider``, or None.

    Used when a team editor syncs a shared connector source: the sync runs
    with the owner's account, the source's own connection when it has one,
    else the owner's first connection for the provider. A connection that is
    not connected (signed out, flagged for reconnect, holding no
    credentials), cannot be decrypted, or has an expired access token that
    can't be refreshed counts as missing.

    Args:
        conn: Open database connection.
        owner_id: The source owner's ``sub``.
        provider: The source's connector provider.
        connection_id: The source's own connection, if it names one.

    Returns:
        Optional[dict]: The connection row, or None when the owner must reconnect.
    """
    from docsgpt.security.encryption import CredentialDecryptionError

    repo = ConnectorSessionsRepository(conn)
    if connection_id:
        row = repo.get_for_user(str(connection_id), owner_id)
        candidates = [row] if owns_connector_session(row, owner_id, provider) else []
    else:
        candidates = [s for s in repo.list_for_user(owner_id) if owns_connector_session(s, owner_id, provider)]
    for session in candidates:
        if service.normalize_status(session) != service.STATUS_CONNECTED:
            continue
        try:
            token_info = service.read_secrets(session).get("token_info") or {}
        except CredentialDecryptionError:
            continue
        if isinstance(token_info, dict) and token_info and not token_info.get("refresh_token"):
            try:
                if ConnectorCreator.create_auth(provider).is_token_expired(token_info):
                    continue
            except Exception:
                # Providers without an expiry check leave the verdict to the sync.
                pass
        return session
    return None


@connectors_ns.route("/api/connectors/sync")
class ConnectorSync(Resource):
    @api.expect(
        api.model(
            "ConnectorSyncModel",
            {
                "source_id": fields.String(required=True, description="Source ID to sync"),
                "connection_id": fields.String(
                    required=False,
                    description="Connection to sync with; defaults to the source's own (ignored for "
                    "team editors, whose sync uses the owner's connection)",
                ),
                "session_token": fields.String(required=False, description="Legacy; use connection_id")
            },
        )
    )
    @api.doc(description="Sync connector source to check for modifications")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)

        try:
            data = request.get_json() or {}
            source_id = data.get('source_id')

            if not source_id:
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "source_id is required"
                    }),
                    400
                )
            user_id = decoded_token.get('sub')
            # Owner or team editor. The sync always runs AS the owner, with the
            # owner's connector account: a grantee can't point the source at
            # their own account (that is ``reconnect``, owner-only).
            try:
                with db_readonly() as conn:
                    source, ra = load_source(conn, source_id, user_id, "edit")
            except AccessDenied as err:
                return make_response(
                    jsonify({"success": False, "error": err.message, "message": err.message}),
                    err.status,
                )
            owner_id = ra.owner_id
            is_owner = ra.access == "owner"

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

            source_connection = str(source['connection_id']) if source.get('connection_id') else None
            if is_owner:
                lookup = dict(data)
                if not (lookup.get('connection_id') or lookup.get('session_token')):
                    if not source_connection:
                        return make_response(
                            jsonify({"success": False, "error": "connection_id is required"}),
                            400,
                        )
                    lookup['connection_id'] = source_connection
                session = service.resolve_request_connection(user_id, source_type, lookup)
                if session is None:
                    return make_response(
                        jsonify({"success": False, "error": "Invalid or unauthorized session"}),
                        401,
                    )
            else:
                # A grantee can't name a connection: theirs would read the
                # source's files with another account.
                with db_readonly() as conn:
                    session = _owner_connector_session(conn, owner_id, source_type, source_connection)
                if session is None:
                    message = (
                        "The owner needs to reconnect this source's account "
                        "before it can be synced."
                    )
                    return make_response(
                        jsonify({"success": False, "error": message, "message": message}),
                        409,
                    )

            # Extract configuration from remote_data
            file_ids = remote_data.get('file_ids', [])
            folder_ids = remote_data.get('folder_ids', [])
            recursive = remote_data.get('recursive', True)

            # Start the sync task
            task = ingest_connector_task.delay(
                job_name=source.get('name'),
                user=owner_id,
                source_type=source_type,
                connection_id=str(session["id"]),
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


