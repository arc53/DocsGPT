import base64
import datetime
import json
import uuid


from bson.objectid import ObjectId
from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    request
)
from flask_restx import fields, Namespace, Resource


from application.api.user.tasks import (
    ingest_connector_task,
)
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.api import api


from application.utils import (
    check_required_fields
)


from application.parser.connectors.connector_creator import ConnectorCreator



mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]
sources_collection = db["sources"]
sessions_collection = db["connector_sessions"]

connector = Blueprint("connector", __name__)
connectors_ns = Namespace("connectors", description="Connector operations", path="/")
api.add_namespace(connectors_ns)



@connectors_ns.route("/api/connectors/upload")
class UploadConnector(Resource):
    @api.expect(
        api.model(
            "ConnectorUploadModel",
            {
                "user": fields.String(required=True, description="User ID"),
                "source": fields.String(
                    required=True, description="Source type (google_drive, github, etc.)"
                ),
                "name": fields.String(required=True, description="Job name"),
                "data": fields.String(required=True, description="Configuration data"),
                "repo_url": fields.String(description="GitHub repository URL"),
            },
        )
    )
    @api.doc(
        description="Uploads connector source for vectorization",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.form
        required_fields = ["user", "source", "name", "data"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            config = json.loads(data["data"])
            source_data = None
            sync_frequency = config.get("sync_frequency", "never")

            if data["source"] == "github":
                source_data = config.get("repo_url")
            elif data["source"] in ["crawler", "url"]:
                source_data = config.get("url")
            elif data["source"] == "reddit":
                source_data = config
            elif data["source"] in ConnectorCreator.get_supported_connectors():
                session_token = config.get("session_token")
                if not session_token:
                    return make_response(jsonify({
                        "success": False,
                        "error": f"Missing session_token in {data['source']} configuration"
                    }), 400)

                file_ids = config.get("file_ids", [])
                if isinstance(file_ids, str):
                    file_ids = [id.strip() for id in file_ids.split(',') if id.strip()]
                elif not isinstance(file_ids, list):
                    file_ids = []

                folder_ids = config.get("folder_ids", [])
                if isinstance(folder_ids, str):
                    folder_ids = [id.strip() for id in folder_ids.split(',') if id.strip()]
                elif not isinstance(folder_ids, list):
                    folder_ids = []

                config["file_ids"] = file_ids
                config["folder_ids"] = folder_ids

                task = ingest_connector_task.delay(
                    job_name=data["name"],
                    user=decoded_token.get("sub"),
                    source_type=data["source"],
                    session_token=session_token,
                    file_ids=file_ids,
                    folder_ids=folder_ids,
                    recursive=config.get("recursive", False),
                    retriever=config.get("retriever", "classic"),
                    sync_frequency=sync_frequency
                )
                return make_response(jsonify({"success": True, "task_id": task.id}), 200)
            task = ingest_connector_task.delay(
                source_data=source_data,
                job_name=data["name"],
                user=decoded_token.get("sub"),
                loader=data["source"],
                sync_frequency=sync_frequency
            )
        except Exception as err:
            current_app.logger.error(
                f"Error uploading connector source: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


@connectors_ns.route("/api/connectors/task_status")
class ConnectorTaskStatus(Resource):
    task_status_model = api.model(
        "ConnectorTaskStatusModel",
        {"task_id": fields.String(required=True, description="Task ID")},
    )

    @api.expect(task_status_model)
    @api.doc(description="Get connector task status")
    def get(self):
        task_id = request.args.get("task_id")
        if not task_id:
            return make_response(
                jsonify({"success": False, "message": "Task ID is required"}), 400
            )
        try:
            from application.celery_init import celery

            task = celery.AsyncResult(task_id)
            task_meta = task.info
            print(f"Task status: {task.status}")
            if not isinstance(
                task_meta, (dict, list, str, int, float, bool, type(None))
            ):
                task_meta = str(task_meta)
        except Exception as err:
            current_app.logger.error(f"Error getting task status: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"status": task.status, "result": task_meta}), 200)


@connectors_ns.route("/api/connectors/sources")
class ConnectorSources(Resource):
    @api.doc(description="Get connector sources")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            sources = sources_collection.find({"user": user, "type": "connector:file"}).sort("date", -1)
            connector_sources = []
            for source in sources:
                connector_sources.append({
                    "id": str(source["_id"]),
                    "name": source.get("name"),
                    "date": source.get("date"),
                    "type": source.get("type"),
                    "source": source.get("source"),
                    "tokens": source.get("tokens", ""),
                    "retriever": source.get("retriever", "classic"),
                    "syncFrequency": source.get("sync_frequency", ""),
                })
        except Exception as err:
            current_app.logger.error(f"Error retrieving connector sources: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(connector_sources), 200)


@connectors_ns.route("/api/connectors/delete")
class DeleteConnectorSource(Resource):
    @api.doc(
        description="Delete a connector source",
        params={"source_id": "The source ID to delete"},
    )
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        source_id = request.args.get("source_id")
        if not source_id:
            return make_response(
                jsonify({"success": False, "message": "source_id is required"}), 400
            )
        try:
            result = sources_collection.delete_one(
                {"_id": ObjectId(source_id), "user": decoded_token.get("sub")}
            )
            if result.deleted_count == 0:
                return make_response(
                    jsonify({"success": False, "message": "Source not found"}), 404
                )
        except Exception as err:
            current_app.logger.error(
                f"Error deleting connector source: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


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

            now = datetime.datetime.now(datetime.timezone.utc)
            result = sessions_collection.insert_one({
                "provider": provider,
                "user": user_id,
                "status": "pending",
                "created_at": now
            })
            state_dict = {
                "provider": provider,
                "object_id": str(result.inserted_id)
            }
            state = base64.urlsafe_b64encode(json.dumps(state_dict).encode()).decode()

            auth = ConnectorCreator.create_auth(provider)
            authorization_url = auth.get_authorization_url(state=state)
            return make_response(jsonify({
                "success": True,
                "authorization_url": authorization_url,
                "state": state
            }), 200)
        except Exception as e:
            current_app.logger.error(f"Error generating connector auth URL: {e}")
            return make_response(jsonify({"success": False, "error": str(e)}), 500)


@connectors_ns.route("/api/connectors/callback")
class ConnectorsCallback(Resource):
    @api.doc(description="Handle OAuth callback for external connectors")
    def get(self):
        """Handle OAuth callback for external connectors"""
        try:
            from application.parser.connectors.connector_creator import ConnectorCreator
            from flask import request, redirect

            authorization_code = request.args.get('code')
            state = request.args.get('state')
            error = request.args.get('error')

            state_dict = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            provider = state_dict["provider"]
            state_object_id = state_dict["object_id"]

            if error:
                if error == "access_denied":
                    return redirect(f"/api/connectors/callback-status?status=cancelled&message=Authentication+was+cancelled.+You+can+try+again+if+you'd+like+to+connect+your+account.&provider={provider}")
                else:
                    current_app.logger.warning(f"OAuth error in callback: {error}")
                    return redirect(f"/api/connectors/callback-status?status=error&message=Authentication+failed.+Please+try+again+and+make+sure+to+grant+all+requested+permissions.&provider={provider}")

            if not authorization_code:
                return redirect(f"/api/connectors/callback-status?status=error&message=Authentication+failed.+Please+try+again+and+make+sure+to+grant+all+requested+permissions.&provider={provider}")

            try:
                auth = ConnectorCreator.create_auth(provider)
                token_info = auth.exchange_code_for_tokens(authorization_code)

                session_token = str(uuid.uuid4())

                try:
                    credentials = auth.create_credentials_from_token_info(token_info)
                    service = auth.build_drive_service(credentials)
                    user_info = service.about().get(fields="user").execute()
                    user_email = user_info.get('user', {}).get('emailAddress', 'Connected User')
                except Exception as e:
                    current_app.logger.warning(f"Could not get user info: {e}")
                    user_email = 'Connected User'

                sanitized_token_info = {
                    "access_token": token_info.get("access_token"),
                    "refresh_token": token_info.get("refresh_token"),
                    "token_uri": token_info.get("token_uri"),
                    "expiry": token_info.get("expiry")
                }

                sessions_collection.find_one_and_update(
                    {"_id": ObjectId(state_object_id), "provider": provider},
                    {
                        "$set": {
                            "session_token": session_token,
                            "token_info": sanitized_token_info,
                            "user_email": user_email,
                            "status": "authorized"
                        }
                    }
                )

                # Redirect to success page with session token and user email
                return redirect(f"/api/connectors/callback-status?status=success&message=Authentication+successful&provider={provider}&session_token={session_token}&user_email={user_email}")

            except Exception as e:
                current_app.logger.error(f"Error exchanging code for tokens: {str(e)}", exc_info=True)
                return redirect(f"/api/connectors/callback-status?status=error&message=Authentication+failed.+Please+try+again+and+make+sure+to+grant+all+requested+permissions.&provider={provider}")

        except Exception as e:
            current_app.logger.error(f"Error handling connector callback: {e}")
            return redirect("/api/connectors/callback-status?status=error&message=Authentication+failed.+Please+try+again+and+make+sure+to+grant+all+requested+permissions.")


@connectors_ns.route("/api/connectors/refresh")
class ConnectorRefresh(Resource):
    @api.expect(api.model("ConnectorRefreshModel", {"provider": fields.String(required=True), "refresh_token": fields.String(required=True)}))
    @api.doc(description="Refresh connector access token")
    def post(self):
        try:
            data = request.get_json()
            provider = data.get('provider')
            refresh_token = data.get('refresh_token')

            if not provider or not refresh_token:
                return make_response(jsonify({"success": False, "error": "provider and refresh_token are required"}), 400)

            auth = ConnectorCreator.create_auth(provider)
            token_info = auth.refresh_access_token(refresh_token)
            return make_response(jsonify({"success": True, "token_info": token_info}), 200)
        except Exception as e:
            current_app.logger.error(f"Error refreshing token for connector: {e}")
            return make_response(jsonify({"success": False, "error": str(e)}), 500)


@connectors_ns.route("/api/connectors/files")
class ConnectorFiles(Resource):
    @api.expect(api.model("ConnectorFilesModel", {
        "provider": fields.String(required=True), 
        "session_token": fields.String(required=True), 
        "folder_id": fields.String(required=False), 
        "limit": fields.Integer(required=False), 
        "page_token": fields.String(required=False),
        "search_query": fields.String(required=False)
    }))
    @api.doc(description="List files from a connector provider (supports pagination and search)")
    def post(self):
        try:
            data = request.get_json()
            provider = data.get('provider')
            session_token = data.get('session_token')
            folder_id = data.get('folder_id')
            limit = data.get('limit', 10)
            page_token = data.get('page_token')
            search_query = data.get('search_query')
            
            if not provider or not session_token:
                return make_response(jsonify({"success": False, "error": "provider and session_token are required"}), 400)

            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)
            user = decoded_token.get('sub')
            session = sessions_collection.find_one({"session_token": session_token, "user": user})
            if not session:
                return make_response(jsonify({"success": False, "error": "Invalid or unauthorized session"}), 401)

            loader = ConnectorCreator.create_connector(provider, session_token)
            input_config = {
                'limit': limit,
                'list_only': True,
                'session_token': session_token,
                'folder_id': folder_id,
                'page_token': page_token
            }
            if search_query:
                input_config['search_query'] = search_query
                
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
            current_app.logger.error(f"Error loading connector files: {e}")
            return make_response(jsonify({"success": False, "error": f"Failed to load files: {str(e)}"}), 500)


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

            session = sessions_collection.find_one({"session_token": session_token, "user": user})
            if not session or "token_info" not in session:
                return make_response(jsonify({"success": False, "error": "Invalid or expired session"}), 401)

            token_info = session["token_info"]
            auth = ConnectorCreator.create_auth(provider)
            is_expired = auth.is_token_expired(token_info)

            if is_expired and token_info.get('refresh_token'):
                try:
                    refreshed_token_info = auth.refresh_access_token(token_info.get('refresh_token'))
                    sanitized_token_info = {
                    "access_token": refreshed_token_info.get("access_token"),
                    "refresh_token": refreshed_token_info.get("refresh_token"),
                    "token_uri": refreshed_token_info.get("token_uri"),
                    "expiry": refreshed_token_info.get("expiry")
                }    
                    sessions_collection.update_one(
                        {"session_token": session_token},
                        {"$set": {"token_info": sanitized_token_info}}
                    )
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

            return make_response(jsonify({
                "success": True,
                "expired": False,
                "user_email": session.get('user_email', 'Connected User'),
                "access_token": token_info.get('access_token')
            }), 200)
        except Exception as e:
            current_app.logger.error(f"Error validating connector session: {e}")
            return make_response(jsonify({"success": False, "error": str(e)}), 500)


@connectors_ns.route("/api/connectors/disconnect")
class ConnectorDisconnect(Resource):
    @api.expect(api.model("ConnectorDisconnectModel", {"provider": fields.String(required=True), "session_token": fields.String(required=False)}))
    @api.doc(description="Disconnect a connector session")
    def post(self):
        try:
            data = request.get_json()
            provider = data.get('provider')
            session_token = data.get('session_token')
            if not provider:
                return make_response(jsonify({"success": False, "error": "provider is required"}), 400)


            if session_token:
                sessions_collection.delete_one({"session_token": session_token})
            
            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            current_app.logger.error(f"Error disconnecting connector session: {e}")
            return make_response(jsonify({"success": False, "error": str(e)}), 500)


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
            source = sources_collection.find_one({"_id": ObjectId(source_id)})
            if not source:
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "Source not found"
                    }), 
                    404
                )

            if source.get('user') != decoded_token.get('sub'):
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "Unauthorized access to source"
                    }), 
                    403
                )

            remote_data = {}
            try:
                if source.get('remote_data'):
                    remote_data = json.loads(source.get('remote_data'))
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
                doc_id=source_id,
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
                    "error": str(err)
                }), 
                400
            )


@connectors_ns.route("/api/connectors/callback-status")
class ConnectorCallbackStatus(Resource):
    @api.doc(description="Return HTML page with connector authentication status")
    def get(self):
        """Return HTML page with connector authentication status"""
        try:
            status = request.args.get('status', 'error')
            message = request.args.get('message', '')
            provider = request.args.get('provider', 'connector')
            session_token = request.args.get('session_token', '')
            user_email = request.args.get('user_email', '')
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>{provider.replace('_', ' ').title()} Authentication</title>
                <style>
                    body {{ font-family: Arial, sans-serif; text-align: center; padding: 40px; }}
                    .container {{ max-width: 600px; margin: 0 auto; }}
                    .success {{ color: #4CAF50; }}
                    .error {{ color: #F44336; }}
                    .cancelled {{ color: #FF9800; }}
                </style>
                <script>
                    window.onload = function() {{
                        const status = "{status}";
                        const sessionToken = "{session_token}";
                        const userEmail = "{user_email}";

                        if (status === "success" && window.opener) {{
                            window.opener.postMessage({{
                                type: '{provider}_auth_success',
                                session_token: sessionToken,
                                user_email: userEmail
                            }}, '*');

                            setTimeout(() => window.close(), 3000);
                        }} else if (status === "cancelled" || status === "error") {{
                            setTimeout(() => window.close(), 3000);
                        }}
                    }};
                </script>
            </head>
            <body>
                <div class="container">
                    <h2>{provider.replace('_', ' ').title()} Authentication</h2>
                    <div class="{status}">
                        <p>{message}</p>
                        {f'<p>Connected as: {user_email}</p>' if status == 'success' else ''}
                    </div>
                    <p><small>You can close this window. {f"Your {provider.replace('_', ' ').title()} is now connected and ready to use." if status == 'success' else "Feel free to close this window."}</small></p>
                </div>
            </body>
            </html>
            """
            
            return make_response(html_content, 200, {'Content-Type': 'text/html'})
        except Exception as e:
            current_app.logger.error(f"Error rendering callback status page: {e}")
            return make_response("Authentication error occurred", 500, {'Content-Type': 'text/html'})


