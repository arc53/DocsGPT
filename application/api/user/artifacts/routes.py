"""Artifact metadata and download routes (parent-derived authz)."""

from __future__ import annotations

import re
from typing import Optional

from flask import (
    Response,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    stream_with_context,
)
from flask_restx import Namespace, Resource

from application.api import api
from application.api.user.artifacts.authz import (
    _shared_row_for,
    authorize_artifact,
    authorize_artifact_write,
    resolve_principal,
    user_can_access_conversation,
)
from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.db.session import db_readonly, db_session
from application.storage.storage_creator import StorageCreator

artifacts_ns = Namespace("artifacts", description="Artifact operations", path="/api")

# Presigned-URL TTL for private S3 artifact downloads (seconds).
_PRESIGNED_URL_TTL = 300


_ARTIFACT_URL_ENVELOPE_MIME = "application/vnd.docsgpt.artifact-url+json"


def _sanitize_header_filename(filename: Optional[str], fallback: str) -> str:
    """Strip CRLF / quotes from a display filename for a Content-Disposition header."""
    if not filename:
        return fallback
    cleaned = re.sub(r'[\r\n"]', "", str(filename)).strip()
    return cleaned or fallback


def _artifact_summary(artifact: dict) -> dict:
    """Project an artifact identity row to its API metadata shape (owner id withheld)."""
    return {
        "id": str(artifact.get("id")),
        "conversation_id": (str(artifact["conversation_id"]) if artifact.get("conversation_id") is not None else None),
        "workflow_run_id": (str(artifact["workflow_run_id"]) if artifact.get("workflow_run_id") is not None else None),
        "message_id": (str(artifact["message_id"]) if artifact.get("message_id") is not None else None),
        "kind": artifact.get("kind"),
        "title": artifact.get("title"),
        "metadata": artifact.get("metadata"),
        "current_version": artifact.get("current_version"),
        "created_at": _iso(artifact.get("created_at")),
        "updated_at": _iso(artifact.get("updated_at")),
    }


def _version_summary(version: dict, *, include_spec: bool = False) -> dict:
    """Project a version row to its API metadata shape (storage_path withheld)."""
    out = {
        "version": version.get("version"),
        "mime_type": version.get("mime_type"),
        "filename": version.get("filename"),
        "size": version.get("size"),
        "sha256": version.get("sha256"),
        "preview_text": version.get("preview_text"),
        "produced_by": version.get("produced_by"),
        "created_at": _iso(version.get("created_at")),
    }
    if include_spec:
        out["spec"] = version.get("spec")
    return out


def _iso(value):
    """ISO-format a datetime, passing through other values unchanged."""
    return value.isoformat() if hasattr(value, "isoformat") else value


@artifacts_ns.route("/artifacts")
class ListArtifacts(Resource):
    @api.doc(description="List artifacts for a conversation, workflow run, or the caller")
    def get(self):
        principal = resolve_principal()
        user_id = principal.user_id
        conversation_id = request.args.get("conversation_id")
        workflow_run_id = request.args.get("workflow_run_id")
        share_token = request.args.get("share_token")

        if not user_id and not share_token:
            return make_response(jsonify({"success": False, "message": "Authentication required"}), 401)

        # Gate UUID-shape before any CAST(:id AS uuid) reaches the repo, so a
        # malformed id is rejected cleanly instead of poisoning the transaction.
        if conversation_id and not looks_like_uuid(conversation_id):
            return make_response(jsonify({"success": False, "message": "Invalid conversation_id"}), 400)
        if workflow_run_id and not looks_like_uuid(workflow_run_id):
            return make_response(jsonify({"success": False, "message": "Invalid workflow_run_id"}), 400)

        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                if principal.is_agent_scoped:
                    # A low-trust agent api_key is embedded in public widget JS and
                    # shared by every anonymous visitor, so it may NOT enumerate the
                    # agent's artifacts. The unguessable conversation_id (UUIDv4) is
                    # the only per-visitor secret: require it as a bearer capability
                    # and scope the query to it. Workflow runs are not agent-scoped,
                    # so reject that filter.
                    if workflow_run_id:
                        return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                    if not conversation_id:
                        return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                    rows = repo.list_artifacts_for_agent(principal.agent_id, user_id, conversation_id=conversation_id)
                elif conversation_id:
                    if not user_can_access_conversation(conn, conversation_id, user_id, share_token):
                        return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                    rows = repo.list_artifacts(conversation_id=conversation_id)
                    # Owner / shared_with collaborator sees every artifact; a
                    # share-token caller is confined to the shared first_n_queries
                    # snapshot (drop artifacts whose message is outside it or NULL).
                    conv_repo = ConversationsRepository(conn)
                    is_owner = bool(user_id and conv_repo.get(conversation_id, user_id) is not None)
                    if not is_owner:
                        shared = _shared_row_for(conn, conversation_id, share_token)
                        first_n = int(shared.get("first_n_queries") or 0) if shared else 0
                        snapshot_ids = conv_repo.first_n_message_ids(conversation_id, first_n)
                        rows = [
                            r
                            for r in rows
                            if r.get("message_id") is not None and str(r.get("message_id")) in snapshot_ids
                        ]
                elif workflow_run_id:
                    run = WorkflowRunsRepository(conn).get(workflow_run_id)
                    if run is None or run.get("user_id") != user_id:
                        return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                    rows = repo.list_artifacts(workflow_run_id=workflow_run_id)
                else:
                    if not user_id:
                        return make_response(
                            jsonify({"success": False, "message": "Authentication required"}),
                            401,
                        )
                    rows = repo.list_artifacts(user_id=user_id)

            return make_response(
                jsonify({"success": True, "artifacts": [_artifact_summary(r) for r in rows]}),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error listing artifacts: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@artifacts_ns.route("/artifacts/<artifact_id>")
class GetArtifact(Resource):
    @api.doc(description="Get an artifact's metadata, version list, and current spec")
    def get(self, artifact_id: str):
        if not looks_like_uuid(artifact_id):
            return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
        principal = resolve_principal()
        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                artifact = repo.get_artifact(artifact_id)
                if artifact is None:
                    return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
                if not authorize_artifact(conn, artifact, principal):
                    return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                versions = repo.list_versions(artifact_id)
                current = repo.get_version(artifact_id, artifact.get("current_version"))

            payload = _artifact_summary(artifact)
            payload["versions"] = [_version_summary(v) for v in versions]
            payload["spec"] = current.get("spec") if current else None
            return make_response(jsonify({"success": True, "artifact": payload}), 200)
        except Exception as err:
            current_app.logger.error(f"Error retrieving artifact: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)

    @api.doc(description="Delete an artifact and all its versions (owner only)")
    def delete(self, artifact_id: str):
        if not looks_like_uuid(artifact_id):
            return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
        principal = resolve_principal()
        try:
            with db_session() as conn:
                repo = ArtifactsRepository(conn)
                artifact = repo.get_artifact(artifact_id)
                if artifact is None:
                    return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
                # Delete is a WRITE: only the parent owner may delete; share
                # links / read-only collaborators are denied (read access only).
                if not authorize_artifact_write(conn, artifact, principal):
                    return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                storage_paths = repo.delete_artifact(artifact_id)
            # Reap the bytes best-effort AFTER the row delete commits.
            _reap_storage(storage_paths)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            current_app.logger.error(f"Error deleting artifact: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


def _reap_storage(paths: list) -> None:
    """Best-effort delete artifact bytes after the DB rows are gone; never raises."""
    if not paths:
        return
    try:
        storage = StorageCreator.get_storage()
    except Exception:
        current_app.logger.warning("artifact delete: storage unavailable", exc_info=True)
        return
    for path in paths:
        try:
            storage.delete_file(path)
        except Exception:
            current_app.logger.warning("artifact delete: failed to delete bytes %s", path, exc_info=True)


@artifacts_ns.route("/artifacts/<artifact_id>/versions/<int:version>")
class GetArtifactVersion(Resource):
    @api.doc(description="Get a single artifact version's metadata and spec")
    def get(self, artifact_id: str, version: int):
        if not looks_like_uuid(artifact_id):
            return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
        principal = resolve_principal()
        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                artifact = repo.get_artifact(artifact_id)
                if artifact is None:
                    return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
                if not authorize_artifact(conn, artifact, principal):
                    return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                version_row = repo.get_version(artifact_id, version)
            if version_row is None:
                return make_response(jsonify({"success": False, "message": "Version not found"}), 404)
            return make_response(
                jsonify({"success": True, "version": _version_summary(version_row, include_spec=True)}),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error retrieving artifact version: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@artifacts_ns.route("/artifacts/<artifact_id>/download")
class DownloadArtifact(Resource):
    @api.doc(description="Download an artifact's bytes (302 to a presigned URL on S3)")
    def get(self, artifact_id: str):
        if not looks_like_uuid(artifact_id):
            return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
        principal = resolve_principal()
        version_arg = request.args.get("version")
        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                artifact = repo.get_artifact(artifact_id)
                if artifact is None:
                    return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
                if not authorize_artifact(conn, artifact, principal):
                    return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                version = artifact.get("current_version")
                if version_arg is not None:
                    try:
                        version = int(version_arg)
                    except ValueError:
                        return make_response(jsonify({"success": False, "message": "Invalid version"}), 400)
                version_row = repo.get_version(artifact_id, version)

            if version_row is None:
                return make_response(jsonify({"success": False, "message": "Version not found"}), 404)
            # The object key is derived only from the stored path, never client input.
            storage_path = version_row.get("storage_path")
            if not storage_path:
                return make_response(jsonify({"success": False, "message": "No file for this version"}), 404)

            filename = _sanitize_header_filename(version_row.get("filename"), f"artifact-{artifact_id}")
            mime_type = version_row.get("mime_type") or "application/octet-stream"
            storage = StorageCreator.get_storage()

            # With URL_STRATEGY=="s3" the contract is to hand back a presigned
            # URL. If the active backend can't mint one, that's a config error:
            # surface a 500 rather than silently proxying bytes from a backend
            # the operator expected to be off the hot path.
            if getattr(settings, "URL_STRATEGY", "backend") == "s3":
                try:
                    url = storage.generate_presigned_url(storage_path, expires_in=_PRESIGNED_URL_TTL)
                except NotImplementedError:
                    current_app.logger.error(
                        "URL_STRATEGY=s3 but %s cannot mint presigned URLs",
                        type(storage).__name__,
                    )
                    return make_response(
                        jsonify({"success": False, "message": "Storage misconfigured"}),
                        500,
                    )
                # A 302 to a cross-origin S3 URL can't be read by the app's authed
                # fetch (the bucket has no CORS grant for the app origin). When the
                # client opts in via ?disposition=url (or Accept: application/json)
                # hand the presigned URL back as JSON so it can navigate to it
                # top-level (no CORS). Default stays a 302 so nothing else breaks.
                if request.args.get("disposition") == "url" or (
                    "application/json" in request.headers.get("Accept", "")
                ):
                    resp = make_response(jsonify({"success": True, "url": url}), 200)
                    # Tag the envelope with a distinctive media type so the client
                    # keys off a server-set signal, not the JSON body shape. A
                    # ``data`` artifact whose bytes happen to be
                    # ``{"success":true,"url":"..."}`` is streamed under the backend
                    # strategy with its own (``application/json``) content-type and
                    # can never carry this vendor type, so it can't be mistaken for a
                    # redirect (open-redirect gadget). Content-Type is CORS-safelisted,
                    # so this stays readable cross-origin without expose-headers.
                    resp.headers["Content-Type"] = _ARTIFACT_URL_ENVELOPE_MIME
                    return resp
                return redirect(url, code=302)

            # Stream the bytes in chunks instead of buffering the whole object in
            # worker memory (artifacts can be many MB); close the handle when done.
            file_obj = storage.get_file(storage_path)

            def _stream():
                try:
                    for chunk in iter(lambda: file_obj.read(65536), b""):
                        yield chunk
                finally:
                    close = getattr(file_obj, "close", None)
                    if callable(close):
                        close()

            return Response(
                stream_with_context(_stream()),
                mimetype=mime_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except FileNotFoundError:
            return make_response(jsonify({"success": False, "message": "File not found"}), 404)
        except Exception as err:
            current_app.logger.error(f"Error downloading artifact: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@artifacts_ns.route("/artifacts/<artifact_id>/restore")
class RestoreArtifact(Resource):
    @api.doc(description="Restore a prior version by appending it as the new current version")
    def post(self, artifact_id: str):
        if not looks_like_uuid(artifact_id):
            return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
        principal = resolve_principal()
        data = request.get_json(silent=True) or {}
        target_version = data.get("version")
        if target_version is None:
            return make_response(jsonify({"success": False, "message": "Missing version"}), 400)
        try:
            target_version = int(target_version)
        except (ValueError, TypeError):
            return make_response(jsonify({"success": False, "message": "Invalid version"}), 400)

        try:
            with db_session() as conn:
                repo = ArtifactsRepository(conn)
                artifact = repo.get_artifact(artifact_id)
                if artifact is None:
                    return make_response(jsonify({"success": False, "message": "Artifact not found"}), 404)
                # Restore is a WRITE (it appends a new current version); share
                # links / shared_with collaborators inherit read access only, so
                # gate on the stricter owner-required write check.
                if not authorize_artifact_write(conn, artifact, principal):
                    return make_response(jsonify({"success": False, "message": "Forbidden"}), 403)
                source = repo.get_version(artifact_id, target_version)
                if source is None:
                    return make_response(jsonify({"success": False, "message": "Version not found"}), 404)
                new_version = repo.append_version(
                    artifact_id,
                    mime_type=source.get("mime_type"),
                    filename=source.get("filename"),
                    storage_path=source.get("storage_path"),
                    size=source.get("size"),
                    sha256=source.get("sha256"),
                    spec=source.get("spec"),
                    preview_text=source.get("preview_text"),
                    produced_by=source.get("produced_by"),
                )
            return make_response(
                jsonify({"success": True, "version": _version_summary(new_version, include_spec=True)}),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error restoring artifact: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
