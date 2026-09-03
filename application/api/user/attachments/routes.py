"""File attachments and media routes."""

import os
import tempfile
from pathlib import Path

import uuid

from flask import Response, current_app, jsonify, make_response, redirect, request
from flask_restx import fields, Namespace, Resource
from werkzeug.datastructures import FileStorage

from application.api import api
from application.cache import get_redis_instance
from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.session import db_readonly
from application.stt.constants import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_AUDIO_MIME_TYPES,
)
from application.stt.upload_limits import (
    AudioFileTooLargeError,
    build_stt_file_size_limit_message,
    enforce_audio_file_size_limit,
    is_audio_filename,
)
from application.stt.live_session import (
    apply_live_stt_hypothesis,
    create_live_stt_session,
    delete_live_stt_session,
    finalize_live_stt_session,
    get_live_stt_transcript_text,
    load_live_stt_session,
    save_live_stt_session,
)
from application.stt.stt_creator import STTCreator
from application.tts.tts_creator import TTSCreator
from application.upload_limits import (
    copy_upload_to_path,
    enforce_parseable_attachment,
    is_unsupported_upload_message,
    UnsupportedUploadTypeError,
    upload_limit_message,
    UploadTooLargeError,
)
from application.utils import (
    get_agent_image_content_type,
    is_external_image_url,
    is_safe_agent_image_path,
    safe_filename,
    verify_agent_image_capability,
)


attachments_ns = Namespace(
    "attachments", description="File attachments and media operations", path="/api"
)

_AGENT_IMAGE_CHUNK_BYTES = 64 * 1024
_AGENT_IMAGE_PRESIGNED_TTL_SECONDS = 300
_AGENT_IMAGE_REDIRECT_CACHE_SECONDS = _AGENT_IMAGE_PRESIGNED_TTL_SECONDS - 60


def _stream_file(file_obj, size_bytes: int):
    """Yield up to the size-checked file range and always close the handle."""
    remaining = size_bytes
    try:
        while remaining > 0:
            chunk = file_obj.read(min(_AGENT_IMAGE_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        file_obj.close()


def _resolve_authenticated_user():
    decoded_token = getattr(request, "decoded_token", None)
    api_key = request.form.get("api_key") or request.args.get("api_key")

    # Return the RAW user identity (not safe_filename'd): the attachment row's
    # ``user_id`` is an identity key that must match the raw ``sub`` used by
    # /stream (initial_user_id) and the artifact authz gate. safe_filename is
    # applied only to the storage path component at write time. (An email-style
    # sub like ``a@b.com`` was previously sanitized to ``abcom``, so the
    # uploaded attachment became unreadable by its own owner on /stream.)
    if decoded_token:
        return decoded_token.get("sub")

    if api_key:
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
        if not agent:
            return make_response(
                jsonify({"success": False, "message": "Invalid API key"}), 401
            )
        return agent.get("user_id")

    return None


def _get_uploaded_file_size(file) -> int:
    try:
        current_position = file.stream.tell()
        file.stream.seek(0, os.SEEK_END)
        size_bytes = file.stream.tell()
        file.stream.seek(current_position)
        return size_bytes
    except Exception:
        return 0


def _is_supported_audio_mimetype(mimetype: str) -> bool:
    if not mimetype:
        return True
    normalized = mimetype.split(";")[0].strip().lower()
    return normalized.startswith("audio/") or normalized in SUPPORTED_AUDIO_MIME_TYPES


def _enforce_uploaded_audio_size_limit(file, filename: str) -> None:
    if not is_audio_filename(filename):
        return
    size_bytes = _get_uploaded_file_size(file)
    if size_bytes:
        enforce_audio_file_size_limit(size_bytes)


def _get_store_attachment_user_error(exc: Exception) -> str:
    if isinstance(exc, AudioFileTooLargeError):
        return build_stt_file_size_limit_message()
    if isinstance(exc, UploadTooLargeError):
        return upload_limit_message()
    if isinstance(exc, UnsupportedUploadTypeError):
        return str(exc)
    return "Failed to process file"


def _require_live_stt_redis():
    redis_client = get_redis_instance()
    if redis_client:
        return redis_client
    return make_response(
        jsonify({"success": False, "message": "Live transcription is unavailable"}),
        503,
    )


def _parse_bool_form_value(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@attachments_ns.route("/store_attachment")
class StoreAttachment(Resource):
    @api.expect(
        api.model(
            "AttachmentModel",
            {
                "file": fields.Raw(required=True, description="File(s) to upload"),
                "api_key": fields.String(
                    required=False, description="API key (optional)"
                ),
            },
        )
    )
    @api.doc(
        description="Stores one or multiple attachments without vectorization or training. Supports user or API key authentication."
    )
    def post(self):
        auth_user = _resolve_authenticated_user()
        if hasattr(auth_user, "status_code"):
            return auth_user
        
        files = request.files.getlist("file")
        if not files:
            single_file = request.files.get("file")
            if single_file:
                files = [single_file]
        
        if not files or all(f.filename == "" for f in files):
            return make_response(
                jsonify({"status": "error", "message": "Missing file(s)"}),
                400,
            )
        
        user = auth_user
        if not user:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}), 401
            )
        
        try:
            from application.api.user.tasks import store_attachment
            from application.api.user.base import storage

            tasks = []
            errors = []
            original_file_count = len(files)
            
            for idx, file in enumerate(files):
                try:
                    attachment_id = uuid.uuid4()
                    original_filename = safe_filename(os.path.basename(file.filename))
                    _enforce_uploaded_audio_size_limit(file, original_filename)
                    # safe_filename only the path component; the DB user_id stays raw.
                    path_user = safe_filename(user)
                    relative_path = (
                        f"{settings.UPLOAD_FOLDER}/{path_user}/attachments/"
                        f"{str(attachment_id)}/{original_filename}"
                    )

                    # Validate a bounded local spool before storage reads it.
                    # This protects local and S3 backends even without a
                    # trustworthy Content-Length header.
                    with tempfile.TemporaryDirectory() as temp_dir:
                        staged_path = os.path.join(temp_dir, original_filename)
                        copy_upload_to_path(file, staged_path)
                        # Refuse here — nothing is stored or queued yet — so a
                        # video the picker let through never reaches the
                        # worker's reader, which would open it as text.
                        enforce_parseable_attachment(staged_path, original_filename)
                        with open(staged_path, "rb") as staged_stream:
                            staged_upload = FileStorage(
                                stream=staged_stream,
                                filename=original_filename,
                                content_type=file.mimetype,
                            )
                            metadata = storage.save_file(
                                staged_upload, relative_path
                            )
                    file_info = {
                        "filename": original_filename,
                        "attachment_id": str(attachment_id),
                        "path": relative_path,
                        "metadata": metadata,
                    }

                    task = store_attachment.delay(file_info, user)
                    tasks.append({
                        "task_id": task.id,
                        "filename": original_filename,
                        "attachment_id": str(attachment_id),
                        "upload_index": idx,
                    })
                except Exception as file_err:
                    current_app.logger.error(f"Error processing file {idx} ({file.filename}): {file_err}", exc_info=True)
                    errors.append({
                        "upload_index": idx,
                        "filename": file.filename,
                        "error": _get_store_attachment_user_error(file_err),
                    })
            
            if not tasks:
                size_limit_messages = {
                    build_stt_file_size_limit_message(),
                    upload_limit_message(),
                }
                if errors and all(
                    error.get("error") in size_limit_messages for error in errors
                ):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": errors[0]["error"],
                                "errors": errors,
                            }
                        ),
                        413,
                    )
                if errors and all(
                    is_unsupported_upload_message(error.get("error")) for error in errors
                ):
                    # Tell the user which type was refused rather than the
                    # generic copy — this is the branch a phone picker that
                    # ignores ``accept`` lands in.
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": errors[0]["error"],
                                "errors": errors,
                            }
                        ),
                        400,
                    )
                return make_response(
                    jsonify({"status": "error", "message": "No valid files to upload"}),
                    400,
                )
            
            if original_file_count == 1 and len(tasks) == 1:
                current_app.logger.info("Returning single task_id response")
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "task_id": tasks[0]["task_id"],
                            # Surface the attachment_id so the frontend
                            # can correlate ``attachment.*`` SSE events
                            # to this row and skip the polling fallback.
                            "attachment_id": tasks[0]["attachment_id"],
                            "message": "File uploaded successfully. Processing started.",
                        }
                    ),
                    200,
                )
            else:
                response_data = {
                    "success": True,
                    "tasks": tasks,
                    "message": f"{len(tasks)} file(s) uploaded successfully. Processing started.",
                }
                if errors:
                    response_data["errors"] = errors
                    response_data["message"] += f" {len(errors)} file(s) failed."
                
                return make_response(
                    jsonify(response_data),
                    200,
                )
        except Exception as err:
            current_app.logger.error(f"Error storing attachment: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to store attachment"}), 400)


@attachments_ns.route("/stt")
class SpeechToText(Resource):
    @api.expect(
        api.model(
            "SpeechToTextModel",
            {
                "file": fields.Raw(required=True, description="Audio file"),
                "language": fields.String(
                    required=False, description="Optional transcription language hint"
                ),
            },
        )
    )
    @api.doc(description="Transcribe an uploaded audio file")
    def post(self):
        auth_user = _resolve_authenticated_user()
        if hasattr(auth_user, "status_code"):
            return auth_user
        if not auth_user:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        file = request.files.get("file")
        if not file or file.filename == "":
            return make_response(
                jsonify({"success": False, "message": "Missing file"}),
                400,
            )

        filename = safe_filename(os.path.basename(file.filename))
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
            return make_response(
                jsonify({"success": False, "message": "Unsupported audio format"}),
                400,
            )

        if not _is_supported_audio_mimetype(file.mimetype or ""):
            return make_response(
                jsonify({"success": False, "message": "Unsupported audio MIME type"}),
                400,
            )

        try:
            _enforce_uploaded_audio_size_limit(file, filename)
        except AudioFileTooLargeError:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": build_stt_file_size_limit_message(),
                    }
                ),
                413,
            )

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                file.save(temp_file.name)
                temp_path = Path(temp_file.name)

            stt_instance = STTCreator.create_stt(settings.STT_PROVIDER)
            transcript = stt_instance.transcribe(
                temp_path,
                language=request.form.get("language") or settings.STT_LANGUAGE,
                timestamps=settings.STT_ENABLE_TIMESTAMPS,
                diarize=settings.STT_ENABLE_DIARIZATION,
            )
            return make_response(jsonify({"success": True, **transcript}), 200)
        except Exception as err:
            current_app.logger.error(f"Error transcribing audio: {err}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Failed to transcribe audio"}),
                400,
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()


@attachments_ns.route("/stt/live/start")
class LiveSpeechToTextStart(Resource):
    @api.doc(description="Start a live speech-to-text session")
    def post(self):
        auth_user = _resolve_authenticated_user()
        if hasattr(auth_user, "status_code"):
            return auth_user
        if not auth_user:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        redis_client = _require_live_stt_redis()
        if hasattr(redis_client, "status_code"):
            return redis_client

        payload = request.get_json(silent=True) or {}
        session_state = create_live_stt_session(
            user=auth_user,
            language=payload.get("language") or settings.STT_LANGUAGE,
        )
        save_live_stt_session(redis_client, session_state)

        return make_response(
            jsonify(
                {
                    "success": True,
                    "session_id": session_state["session_id"],
                    "language": session_state.get("language"),
                    "committed_text": "",
                    "mutable_text": "",
                    "previous_hypothesis": "",
                    "latest_hypothesis": "",
                    "finalized_text": "",
                    "pending_text": "",
                    "transcript_text": "",
                }
            ),
            200,
        )


@attachments_ns.route("/stt/live/chunk")
class LiveSpeechToTextChunk(Resource):
    @api.expect(
        api.model(
            "LiveSpeechToTextChunkModel",
            {
                "session_id": fields.String(
                    required=True, description="Live transcription session ID"
                ),
                "chunk_index": fields.Integer(
                    required=True, description="Sequential chunk index"
                ),
                "is_silence": fields.Boolean(
                    required=False,
                    description="Whether the latest capture window was mostly silence",
                ),
                "file": fields.Raw(required=True, description="Audio chunk"),
            },
        )
    )
    @api.doc(description="Transcribe a chunk for a live speech-to-text session")
    def post(self):
        auth_user = _resolve_authenticated_user()
        if hasattr(auth_user, "status_code"):
            return auth_user
        if not auth_user:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        redis_client = _require_live_stt_redis()
        if hasattr(redis_client, "status_code"):
            return redis_client

        session_id = request.form.get("session_id", "").strip()
        if not session_id:
            return make_response(
                jsonify({"success": False, "message": "Missing session_id"}),
                400,
            )

        session_state = load_live_stt_session(redis_client, session_id)
        if not session_state:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Live transcription session not found",
                    }
                ),
                404,
            )

        # The stored ``user`` is the RAW sub (see _resolve_authenticated_user), and
        # auth_user is also raw, so compare raw-vs-raw -- never safe_filename'd, or an
        # email-style sub (a@b.com) would 403 the owner on their own session.
        if str(session_state.get("user", "")) != auth_user:
            return make_response(
                jsonify({"success": False, "message": "Forbidden"}),
                403,
            )

        chunk_index_raw = request.form.get("chunk_index", "").strip()
        if chunk_index_raw == "":
            return make_response(
                jsonify({"success": False, "message": "Missing chunk_index"}),
                400,
            )

        try:
            chunk_index = int(chunk_index_raw)
        except ValueError:
            return make_response(
                jsonify({"success": False, "message": "Invalid chunk_index"}),
                400,
            )
        is_silence = _parse_bool_form_value(request.form.get("is_silence"))

        file = request.files.get("file")
        if not file or file.filename == "":
            return make_response(
                jsonify({"success": False, "message": "Missing file"}),
                400,
            )

        filename = safe_filename(os.path.basename(file.filename))
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
            return make_response(
                jsonify({"success": False, "message": "Unsupported audio format"}),
                400,
            )

        if not _is_supported_audio_mimetype(file.mimetype or ""):
            return make_response(
                jsonify({"success": False, "message": "Unsupported audio MIME type"}),
                400,
            )

        try:
            _enforce_uploaded_audio_size_limit(file, filename)
        except AudioFileTooLargeError:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": build_stt_file_size_limit_message(),
                    }
                ),
                413,
            )

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                file.save(temp_file.name)
                temp_path = Path(temp_file.name)

            session_language = session_state.get("language") or settings.STT_LANGUAGE
            stt_instance = STTCreator.create_stt(settings.STT_PROVIDER)
            transcript = stt_instance.transcribe(
                temp_path,
                language=session_language,
                timestamps=False,
                diarize=False,
            )
            if not session_state.get("language") and transcript.get("language"):
                session_state["language"] = transcript["language"]

            try:
                apply_live_stt_hypothesis(
                    session_state,
                    str(transcript.get("text", "")),
                    chunk_index,
                    is_silence=is_silence,
                )
            except ValueError:
                current_app.logger.warning(
                    "Invalid live transcription chunk",
                    exc_info=True,
                )
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Invalid live transcription chunk",
                        }
                    ),
                    409,
                )
            save_live_stt_session(redis_client, session_state)

            return make_response(
                jsonify(
                    {
                        "success": True,
                        "session_id": session_id,
                        "chunk_index": chunk_index,
                        "chunk_text": transcript.get("text", ""),
                        "is_silence": is_silence,
                        "language": session_state.get("language"),
                        "committed_text": session_state.get("committed_text", ""),
                        "mutable_text": session_state.get("mutable_text", ""),
                        "previous_hypothesis": session_state.get(
                            "previous_hypothesis", ""
                        ),
                        "latest_hypothesis": session_state.get(
                            "latest_hypothesis", ""
                        ),
                        "finalized_text": session_state.get("committed_text", ""),
                        "pending_text": session_state.get("mutable_text", ""),
                        "transcript_text": get_live_stt_transcript_text(session_state),
                    }
                ),
                200,
            )
        except Exception as err:
            current_app.logger.error(
                f"Error transcribing live audio chunk: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Failed to transcribe audio"}),
                400,
            )
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()


@attachments_ns.route("/stt/live/finish")
class LiveSpeechToTextFinish(Resource):
    @api.doc(description="Finish a live speech-to-text session")
    def post(self):
        auth_user = _resolve_authenticated_user()
        if hasattr(auth_user, "status_code"):
            return auth_user
        if not auth_user:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        redis_client = _require_live_stt_redis()
        if hasattr(redis_client, "status_code"):
            return redis_client

        payload = request.get_json(silent=True) or {}
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            return make_response(
                jsonify({"success": False, "message": "Missing session_id"}),
                400,
            )

        session_state = load_live_stt_session(redis_client, session_id)
        if not session_state:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Live transcription session not found",
                    }
                ),
                404,
            )

        # Stored ``user`` and auth_user are both RAW subs; compare raw-vs-raw so an
        # email-style sub owner is not 403'd on their own finish call.
        if str(session_state.get("user", "")) != auth_user:
            return make_response(
                jsonify({"success": False, "message": "Forbidden"}),
                403,
            )

        final_text = finalize_live_stt_session(session_state)
        delete_live_stt_session(redis_client, session_id)

        return make_response(
            jsonify(
                {
                    "success": True,
                    "session_id": session_id,
                    "language": session_state.get("language"),
                    "text": final_text,
                }
            ),
            200,
        )


@attachments_ns.route("/images/<string:agent_id>/<string:capability>")
class ServeImage(Resource):
    @api.doc(description="Serve an agent image using an opaque capability URL")
    def get(self, agent_id, capability):
        try:
            if not looks_like_uuid(agent_id):
                return make_response(
                    jsonify({"success": False, "message": "Image not found"}), 404
                )
            with db_readonly() as conn:
                agent = AgentsRepository(conn).find_image_record(agent_id)
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Image not found"}), 404
                )

            image_path = agent.get("image")
            user_id = agent.get("user_id")
            content_type = get_agent_image_content_type(image_path)
            if (
                is_external_image_url(image_path)
                or not content_type
                or not is_safe_agent_image_path(image_path, user_id)
                or not verify_agent_image_capability(
                    capability, agent_id, image_path, user_id
                )
            ):
                return make_response(
                    jsonify({"success": False, "message": "Image not found"}), 404
                )

            from application.api.user.base import storage

            size_bytes = storage.get_file_size(image_path)
            if size_bytes < 0 or size_bytes > settings.AGENT_IMAGE_MAX_BYTES:
                current_app.logger.warning(
                    "Rejected oversized legacy agent image for agent %s", agent_id
                )
                return make_response(
                    jsonify({"success": False, "message": "Image not found"}), 404
                )

            if settings.STORAGE_TYPE == "s3":
                image_url = storage.generate_presigned_url(
                    image_path,
                    expires_in=_AGENT_IMAGE_PRESIGNED_TTL_SECONDS,
                    content_type=content_type,
                )
                response = redirect(image_url, code=302)
                response.headers.set(
                    "Cache-Control",
                    f"private, max-age={_AGENT_IMAGE_REDIRECT_CACHE_SECONDS}",
                )
                response.headers.set("X-Content-Type-Options", "nosniff")
                return response

            file_obj = storage.get_file(image_path)
            response = Response(
                _stream_file(file_obj, size_bytes),
                content_type=content_type,
                direct_passthrough=True,
            )
            response.headers.set("Cache-Control", "public, max-age=86400, immutable")
            response.headers.set("X-Content-Type-Options", "nosniff")

            return response
        except FileNotFoundError:
            return make_response(
                jsonify({"success": False, "message": "Image not found"}), 404
            )
        except ValueError:
            return make_response(
                jsonify({"success": False, "message": "Image not found"}), 404
            )
        except Exception as e:
            current_app.logger.error(f"Error serving image: {e}")
            return make_response(
                jsonify({"success": False, "message": "Error retrieving image"}), 500
            )


@attachments_ns.route("/tts")
class TextToSpeech(Resource):
    tts_model = api.model(
        "TextToSpeechModel",
        {
            "text": fields.String(
                required=True, description="Text to be synthesized as audio"
            ),
        },
    )

    @api.expect(tts_model)
    @api.doc(description="Synthesize audio speech from text")
    def post(self):
        data = request.get_json()
        text = data["text"]
        try:
            tts_instance = TTSCreator.create_tts(settings.TTS_PROVIDER)
            audio_base64, detected_language = tts_instance.text_to_speech(text)
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "audio_base64": audio_base64,
                        "lang": detected_language,
                    }
                ),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error synthesizing audio: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
