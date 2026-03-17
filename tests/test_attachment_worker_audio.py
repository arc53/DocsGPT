from bson import ObjectId
from unittest.mock import MagicMock, patch

from application.parser.schema.base import Document


def test_attachment_worker_persists_transcript_metadata(mock_mongo_db):
    from application.worker import attachment_worker

    task = MagicMock()
    mock_storage = MagicMock()
    mock_storage.process_file.return_value = Document(
        text="transcribed meeting notes",
        extra_info={
            "transcript_language": "en",
            "transcript_duration_s": 12.5,
            "transcript_provider": "openai",
        },
    )
    file_info = {
        "filename": "meeting.wav",
        "attachment_id": "507f1f77bcf86cd799439011",
        "path": "inputs/test_user/attachments/507f1f77bcf86cd799439011/meeting.wav",
        "metadata": {"storage_type": "local"},
    }

    with patch(
        "application.worker.StorageCreator.get_storage",
        return_value=mock_storage,
    ), patch("application.worker.num_tokens_from_string", return_value=10):
        result = attachment_worker(task, file_info, "test_user")

    stored_attachment = mock_mongo_db["docsgpt"]["attachments"].find_one(
        {"_id": ObjectId(result["attachment_id"])}
    )

    assert stored_attachment is not None
    assert stored_attachment["metadata"]["storage_type"] == "local"
    assert stored_attachment["metadata"]["transcript_language"] == "en"
    assert stored_attachment["metadata"]["transcript_duration_s"] == 12.5
    assert stored_attachment["metadata"]["transcript_provider"] == "openai"


def test_attachment_worker_preserves_reader_metadata_for_audio(
    mock_mongo_db, tmp_path
):
    from application.worker import attachment_worker

    task = MagicMock()
    mock_storage = MagicMock()
    fake_audio_file = tmp_path / "meeting.wav"
    fake_audio_file.write_bytes(b"audio-bytes")

    fake_parser = MagicMock()
    fake_parser.parser_config_set = True
    fake_parser.parse_file.return_value = "transcribed meeting notes"
    fake_parser.get_file_metadata.return_value = {
        "transcript_language": "en",
        "transcript_duration_s": 12.5,
        "transcript_provider": "openai",
    }

    def process_file(path, processor_func, **kwargs):
        _ = path, kwargs
        return processor_func(local_path=str(fake_audio_file))

    mock_storage.process_file.side_effect = process_file
    file_info = {
        "filename": "meeting.wav",
        "attachment_id": "507f1f77bcf86cd799439012",
        "path": "inputs/test_user/attachments/507f1f77bcf86cd799439012/meeting.wav",
        "metadata": {"storage_type": "local"},
    }

    with patch(
        "application.worker.StorageCreator.get_storage",
        return_value=mock_storage,
    ), patch(
        "application.worker.get_default_file_extractor",
        return_value={".wav": fake_parser},
    ), patch("application.worker.num_tokens_from_string", return_value=10):
        result = attachment_worker(task, file_info, "test_user")

    stored_attachment = mock_mongo_db["docsgpt"]["attachments"].find_one(
        {"_id": ObjectId(result["attachment_id"])}
    )

    assert stored_attachment is not None
    assert stored_attachment["metadata"]["transcript_language"] == "en"
    assert stored_attachment["metadata"]["transcript_duration_s"] == 12.5
    assert stored_attachment["metadata"]["transcript_provider"] == "openai"
