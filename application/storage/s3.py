"""S3 storage implementation."""
import io
from typing import BinaryIO, List, Callable

import boto3
from botocore.exceptions import ClientError

from application.storage.base import BaseStorage


class S3Storage(BaseStorage):
    """AWS S3 storage implementation."""
    
    def __init__(self, bucket_name: str, aws_access_key_id=None, 
                 aws_secret_access_key=None, region_name=None):
        """
        Initialize S3 storage.
        
        Args:
            bucket_name: S3 bucket name
            aws_access_key_id: AWS access key ID (optional if using IAM roles)
            aws_secret_access_key: AWS secret access key (optional if using IAM roles)
            region_name: AWS region name (optional)
        """
        self.bucket_name = bucket_name
        
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name
        )
    
    def save_file(self, file_data: BinaryIO, path: str) -> str:
        """Save a file to S3 storage."""
        self.s3.upload_fileobj(file_data, self.bucket_name, path)
        return path
    
    def get_file(self, path: str) -> BinaryIO:
        """Get a file from S3 storage."""
        if not self.file_exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        
        file_obj = io.BytesIO()
        self.s3.download_fileobj(self.bucket_name, path, file_obj)
        file_obj.seek(0)
        return file_obj
    
    def delete_file(self, path: str) -> bool:
        """Delete a file from S3 storage."""
        try:
            self.s3.delete_object(Bucket=self.bucket_name, Key=path)
            return True
        except ClientError:
            return False
    
    def file_exists(self, path: str) -> bool:
        """Check if a file exists in S3 storage."""
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=path)
            return True
        except ClientError:
            return False
    
    def list_files(self, directory: str) -> List[str]:
        """List all files in a directory in S3 storage."""
        # Ensure directory ends with a slash if it's not empty
        if directory and not directory.endswith('/'):
            directory += '/'
            
        result = []
        paginator = self.s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=directory)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    result.append(obj['Key'])
                    
        return result

    def process_file(self, path: str, processor_func: Callable, **kwargs):
        """
        Process a file using the provided processor function.
        
        For S3 storage, we need to download the file to a temporary location first.
        
        Args:
            path: Path to the file
            processor_func: Function that processes the file
            **kwargs: Additional arguments to pass to the processor function
            
        Returns:
            The result of the processor function
        """
        import tempfile
        import os
        
        if not self.file_exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            self.s3.download_fileobj(self.bucket_name, path, temp_file)
            temp_path = temp_file.name
        
        try:
            result = processor_func(file_path=temp_path, **kwargs)
            return result
        finally:
            try:
                os.unlink(temp_path)
            except Exception as e:
                import logging
                logging.warning(f"Failed to delete temporary file: {e}")
