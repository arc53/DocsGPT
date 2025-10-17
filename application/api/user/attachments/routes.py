"""File attachments and media routes."""

import os

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import agents_collection, storage
from application.api.user.tasks import store_attachment
from application.core.settings import settings
from application.tts.tts_creator import TTSCreator
from application.utils import safe_filename


attachments_ns = Namespace(
    "attachments", description="File attachments and media operations", path="/api"
)


@attachments_ns.route("/store_attachment")
class StoreAttachment(Resource):
    @api.expect(
        api.model(
            "AttachmentModel",
            {
                "file": fields.Raw(required=True, description="File to upload"),
                "api_key": fields.String(
                    required=False, description="API key (optional)"
                ),
            },
        )
    )
    @api.doc(
        description="Stores a single attachment without vectorization or training. Supports user or API key authentication."
    )
    def post(self):
        decoded_token = getattr(request, "decoded_token", None)
        api_key = request.form.get("api_key") or request.args.get("api_key")
        file = request.files.get("file")

        if not file or file.filename == "":
            return make_response(
                jsonify({"status": "error", "message": "Missing file"}),
                400,
            )
        user = None
        if decoded_token:
            user = safe_filename(decoded_token.get("sub"))
        elif api_key:
            agent = agents_collection.find_one({"key": api_key})
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Invalid API key"}), 401
                )
            user = safe_filename(agent.get("user"))
        else:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}), 401
            )
        try:
            attachment_id = ObjectId()
            original_filename = safe_filename(os.path.basename(file.filename))
            relative_path = f"{settings.UPLOAD_FOLDER}/{user}/attachments/{str(attachment_id)}/{original_filename}"

            metadata = storage.save_file(file, relative_path)

            file_info = {
                "filename": original_filename,
                "attachment_id": str(attachment_id),
                "path": relative_path,
                "metadata": metadata,
            }

            task = store_attachment.delay(file_info, user)

            return make_response(
                jsonify(
                    {
                        "success": True,
                        "task_id": task.id,
                        "message": "File uploaded successfully. Processing started.",
                    }
                ),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error storing attachment: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": str(err)}), 400)


@attachments_ns.route("/images/<path:image_path>")
class ServeImage(Resource):
    @api.doc(description="Serve an image from storage")
    def get(self, image_path):
        try:
            file_obj = storage.get_file(image_path)
            extension = image_path.split(".")[-1].lower()
            content_type = f"image/{extension}"
            if extension == "jpg":
                content_type = "image/jpeg"
            response = make_response(file_obj.read())
            response.headers.set("Content-Type", content_type)
            response.headers.set("Cache-Control", "max-age=86400")

            return response
        except FileNotFoundError:
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
