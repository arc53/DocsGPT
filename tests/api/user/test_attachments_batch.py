"""Comprehensive test suite for batch attachment upload functionality."""

import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

from werkzeug.datastructures import FileStorage
import pytest

from application.api.user.attachments.routes import StoreAttachment
from application.worker import attachment_worker
from application.storage.base import BaseStorage


class TestBatchAttachmentUpload(unittest.TestCase):
    """Test suite for batch attachment upload functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.store_attachment = StoreAttachment()
        self.test_user = "test_user"
        self.sample_files = [
            ("test1.txt", b"Sample content 1", "text/plain"),
            ("test2.pdf", b"Sample PDF content", "application/pdf"),
            ("test3.docx", b"Sample document content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        ]
    
    def create_file_storage(self, filename, content, mimetype="text/plain"):
        """Create a FileStorage object for testing."""
        file_obj = BytesIO(content)
        return FileStorage(
            stream=file_obj,
            filename=filename,
            content_type=mimetype
        )
    
    def test_file_existence_verification_single_file(self):
        """Test file existence verification for single file upload."""
        with patch('application.api.user.attachments.routes.storage') as mock_storage:
            # Mock successful file save and verification
            mock_storage.save_file.return_value = {"storage_type": "local"}
            mock_storage.file_exists.return_value = True
            mock_storage.get_file.return_value = Mock()
            
            with patch('application.api.user.attachments.routes.store_attachment') as mock_task:
                mock_task.delay.return_value = Mock(id="test-task-id")
                
                # Test single file processing
                test_file = self.create_file_storage("test.txt", b"content")
                result = self.store_attachment._process_single_file(test_file, self.test_user)
                
                # Verify file existence was checked
                mock_storage.file_exists.assert_called()
                mock_storage.get_file.assert_called()
                
                # Verify successful result
                self.assertTrue(result["success"])
                self.assertEqual(result["filename"], "test.txt")
                self.assertIsNotNone(result["attachment_id"])
                self.assertEqual(result["task_id"], "test-task-id")
    
    def test_file_verification_retry_mechanism(self):
        """Test retry mechanism when file verification initially fails."""
        with patch('application.api.user.attachments.routes.storage') as mock_storage:
            mock_storage.save_file.return_value = {"storage_type": "local"}
            
            # Mock file_exists to fail first two attempts, succeed on third
            mock_storage.file_exists.side_effect = [False, False, True]
            mock_storage.get_file.return_value = Mock()
            
            with patch('application.api.user.attachments.routes.store_attachment') as mock_task:
                mock_task.delay.return_value = Mock(id="test-task-id")
                
                with patch('time.sleep') as mock_sleep:
                    test_file = self.create_file_storage("test.txt", b"content")
                    result = self.store_attachment._process_single_file(test_file, self.test_user)
                    
                    # Verify retry logic was executed
                    self.assertEqual(mock_storage.file_exists.call_count, 3)
                    self.assertEqual(mock_sleep.call_count, 2)  # Two retry delays
                    
                    # Verify successful result after retries
                    self.assertTrue(result["success"])
    
    def test_file_verification_failure_after_max_retries(self):
        """Test failure handling when file verification fails after max retries."""
        with patch('application.api.user.attachments.routes.storage') as mock_storage:
            mock_storage.save_file.return_value = {"storage_type": "local"}
            mock_storage.file_exists.return_value = False  # Always fail
            mock_storage.delete_file.return_value = True  # Cleanup succeeds
            
            with patch('time.sleep'):
                test_file = self.create_file_storage("test.txt", b"content")
                result = self.store_attachment._process_single_file(test_file, self.test_user)
                
                # Verify failure result
                self.assertFalse(result["success"])
                self.assertIn("File upload failed", result["message"])
                self.assertIn("verification failed", result["error"])
                
                # Verify cleanup was attempted
                mock_storage.delete_file.assert_called()
    
    def test_batch_processing_mixed_success_failure(self):
        """Test batch processing with mixed success and failure scenarios."""
        with patch('application.api.user.attachments.routes.storage') as mock_storage:
            # Configure mock to succeed for first file, fail for second, succeed for third
            def mock_process_single_file(file, user):
                filename = getattr(file, 'filename', 'unknown')
                if filename == 'test1.txt':
                    return {
                        "success": True,
                        "filename": filename,
                        "attachment_id": "id1",
                        "task_id": "task1",
                        "message": "Success"
                    }
                elif filename == 'test2.pdf':
                    return {
                        "success": False,
                        "filename": filename,
                        "attachment_id": "id2",
                        "task_id": None,
                        "message": "Processing failed",
                        "error": "Mock failure"
                    }
                else:  # test3.docx
                    return {
                        "success": True,
                        "filename": filename,
                        "attachment_id": "id3",
                        "task_id": "task3",
                        "message": "Success"
                    }
            
            with patch.object(self.store_attachment, '_process_single_file', side_effect=mock_process_single_file):
                files = [
                    self.create_file_storage(*file_data) for file_data in self.sample_files
                ]
                
                results = self.store_attachment._process_files_batch(files, self.test_user)
                
                # Verify results
                self.assertEqual(len(results), 3)
                self.assertTrue(results[0]["success"])  # test1.txt succeeded
                self.assertFalse(results[1]["success"])  # test2.pdf failed
                self.assertTrue(results[2]["success"])  # test3.docx succeeded
                
                # Verify error isolation
                self.assertIsNone(results[1]["task_id"])
                self.assertIsNotNone(results[0]["task_id"])
                self.assertIsNotNone(results[2]["task_id"])
    
    def test_worker_retry_mechanism(self):
        """Test the worker retry mechanism for FileNotFoundError."""
        # Mock the worker task context
        mock_self = Mock()
        mock_self.update_state = Mock()
        
        file_info = {
            "filename": "test.txt",
            "attachment_id": "test-id",
            "path": "test/path/test.txt",
            "metadata": {}
        }
        
        with patch('application.worker.StorageCreator') as mock_storage_creator:
            mock_storage = Mock()
            mock_storage_creator.get_storage.return_value = mock_storage
            
            # Mock file_exists to fail first two attempts, succeed on third
            mock_storage.file_exists.side_effect = [False, False, True]
            mock_storage.get_file.return_value = Mock()
            mock_storage.process_file.return_value = "Sample content for processing"
            
            with patch('application.worker.MongoDB') as mock_mongo:
                mock_db = Mock()
                mock_collection = Mock()
                mock_mongo.get_client.return_value = {"test_db": mock_db}
                mock_db.__getitem__ = lambda self, key: mock_collection
                
                with patch('application.worker.settings') as mock_settings:
                    mock_settings.MONGO_DB_NAME = "test_db"
                    
                    with patch('time.sleep') as mock_sleep:
                        # Call the worker function
                        result = attachment_worker(mock_self, file_info, self.test_user)
                        
                        # Verify retry logic was executed
                        self.assertEqual(mock_storage.file_exists.call_count, 3)
                        self.assertEqual(mock_sleep.call_count, 2)
                        
                        # Verify successful processing
                        self.assertEqual(result["filename"], "test.txt")
                        self.assertEqual(result["attachment_id"], "test-id")
    
    def test_worker_failure_after_max_retries(self):
        """Test worker failure handling after exhausting all retries."""
        mock_self = Mock()
        mock_self.update_state = Mock()
        
        file_info = {
            "filename": "test.txt",
            "attachment_id": "test-id", 
            "path": "test/path/test.txt",
            "metadata": {}
        }
        
        with patch('application.worker.StorageCreator') as mock_storage_creator:
            mock_storage = Mock()
            mock_storage_creator.get_storage.return_value = mock_storage
            mock_storage.file_exists.return_value = False  # Always fail
            
            with patch('time.sleep'):
                with pytest.raises(Exception) as exc_info:
                    attachment_worker(mock_self, file_info, self.test_user)
                
                # Verify the error message contains retry information
                self.assertIn("3 attempts", str(exc_info.value))
                self.assertIn("test.txt", str(exc_info.value))
    
    def test_backward_compatibility_single_file(self):
        """Test backward compatibility with existing single file upload API."""
        with patch('application.api.user.attachments.routes.storage') as mock_storage:
            mock_storage.save_file.return_value = {"storage_type": "local"}
            mock_storage.file_exists.return_value = True
            mock_storage.get_file.return_value = Mock()
            
            with patch('application.api.user.attachments.routes.store_attachment') as mock_task:
                mock_task.delay.return_value = Mock(id="test-task-id")
                
                # Test with single file (backward compatibility)
                test_file = self.create_file_storage("single.txt", b"single file content")
                results = self.store_attachment._process_files_batch([test_file], self.test_user)
                
                # Verify single result in array format
                self.assertEqual(len(results), 1)
                result = results[0]
                
                # Verify backward-compatible response structure
                self.assertTrue(result["success"])
                self.assertEqual(result["filename"], "single.txt")
                self.assertIsNotNone(result["attachment_id"])
                self.assertEqual(result["task_id"], "test-task-id")
                self.assertEqual(result["message"], "File uploaded successfully. Processing started.")
    
    def test_empty_file_handling(self):
        """Test handling of empty or invalid files."""
        # Test with empty filename
        empty_file = self.create_file_storage("", b"content")
        result = self.store_attachment._process_single_file(empty_file, self.test_user)
        
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Empty or invalid file")
        self.assertIn("empty or has no filename", result["error"])
        
        # Test with None file
        result = self.store_attachment._process_single_file(None, self.test_user)
        
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Empty or invalid file")
    
    def test_authentication_methods(self):
        """Test different authentication methods."""
        # Test JWT token authentication
        with patch('application.api.user.attachments.routes.request') as mock_request:
            mock_request.decoded_token = {"sub": "jwt_user"}
            mock_request.form.get.return_value = None
            mock_request.args.get.return_value = None
            
            user, error = self.store_attachment._authenticate_user()
            
            self.assertEqual(user, "jwt_user")
            self.assertIsNone(error)
        
        # Test API key authentication
        with patch('application.api.user.attachments.routes.request') as mock_request:
            mock_request.decoded_token = None
            mock_request.form.get.return_value = "test_api_key"
            mock_request.args.get.return_value = None
            
            with patch('application.api.user.attachments.routes.agents_collection') as mock_collection:
                mock_collection.find_one.return_value = {"user": "api_user"}
                
                user, error = self.store_attachment._authenticate_user()
                
                self.assertEqual(user, "api_user")
                self.assertIsNone(error)
        
        # Test authentication failure
        with patch('application.api.user.attachments.routes.request') as mock_request:
            mock_request.decoded_token = None
            mock_request.form.get.return_value = None
            mock_request.args.get.return_value = None
            
            user, error = self.store_attachment._authenticate_user()
            
            self.assertIsNone(user)
            self.assertIsNotNone(error)
    
    def test_logging_and_monitoring(self):
        """Test comprehensive logging for debugging and monitoring."""
        with patch('application.api.user.attachments.routes.current_app') as mock_app:
            mock_logger = Mock()
            mock_app.logger = mock_logger
            
            with patch('application.api.user.attachments.routes.storage') as mock_storage:
                mock_storage.save_file.return_value = {"storage_type": "local"}
                mock_storage.file_exists.return_value = True
                mock_storage.get_file.return_value = Mock()
                
                with patch('application.api.user.attachments.routes.store_attachment') as mock_task:
                    mock_task.delay.return_value = Mock(id="test-task-id")
                    
                    files = [self.create_file_storage("test.txt", b"content")]
                    self.store_attachment._process_files_batch(files, self.test_user)
                    
                    # Verify logging calls
                    self.assertTrue(mock_logger.info.called)
                    self.assertTrue(mock_logger.debug.called)
                    
                    # Check for specific log messages
                    log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
                    self.assertTrue(any("Processing file" in msg for msg in log_calls))
                    self.assertTrue(any("Successfully queued" in msg for msg in log_calls))
    
    def test_performance_metrics(self):
        """Test performance tracking and metrics collection."""
        with patch('application.worker.time') as mock_time:
            # Mock time progression
            mock_time.time.side_effect = [0.0, 0.5, 1.0, 1.5, 2.0]  # 2 second total
            
            mock_self = Mock()
            mock_self.update_state = Mock()
            
            file_info = {
                "filename": "perf_test.txt",
                "attachment_id": "perf-test-id",
                "path": "test/path/perf_test.txt",
                "metadata": {}
            }
            
            with patch('application.worker.StorageCreator') as mock_storage_creator:
                mock_storage = Mock()
                mock_storage_creator.get_storage.return_value = mock_storage
                mock_storage.file_exists.return_value = True
                mock_storage.get_file.return_value = Mock()
                mock_storage.process_file.return_value = "Performance test content"
                
                with patch('application.worker.MongoDB') as mock_mongo:
                    mock_db = Mock()
                    mock_collection = Mock()
                    mock_mongo.get_client.return_value = {"test_db": mock_db}
                    mock_db.__getitem__ = lambda self, key: mock_collection
                    
                    with patch('application.worker.settings') as mock_settings:
                        mock_settings.MONGO_DB_NAME = "test_db"
                        
                        result = attachment_worker(mock_self, file_info, self.test_user)
                        
                        # Verify performance stats are included
                        self.assertIn("processing_stats", result)
                        stats = result["processing_stats"]
                        self.assertIn("total_time", stats)
                        self.assertIn("attempts_needed", stats)


if __name__ == '__main__':
    unittest.main()
