"""S3 storage implementation."""

import io
import os
from typing import BinaryIO, Callable, List

import boto3
from application.core.settings import settings

from application.storage.base import BaseStorage
from botocore.exceptions import ClientError


class S3Storage(BaseStorage):
    """AWS S3 storage implementation."""

    def __init__(self, bucket_name=None):
        """
        Initialize S3 storage.

        Args:
            bucket_name: S3 bucket name (optional, defaults to settings)
        """
        self.bucket_name = bucket_name or getattr(
            settings, "S3_BUCKET_NAME", "docsgpt-test-bucket"
        )

        # Get credentials from settings

        aws_access_key_id = getattr(settings, "SAGEMAKER_ACCESS_KEY", None)
        aws_secret_access_key = getattr(settings, "SAGEMAKER_SECRET_KEY", None)
        region_name = getattr(settings, "SAGEMAKER_REGION", None)

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

    def save_file(
        self,
        file_data: BinaryIO,
        path: str,
        storage_class: str = "INTELLIGENT_TIERING",
        **kwargs,
    ) -> dict:
        """Save a file to S3 storage."""
        self.s3.upload_fileobj(
            file_data, self.bucket_name, path, ExtraArgs={"StorageClass": storage_class}
        )

        region = getattr(settings, "SAGEMAKER_REGION", None)

        return {
            "storage_type": "s3",
            "bucket_name": self.bucket_name,
            "uri": f"s3://{self.bucket_name}/{path}",
            "region": region,
        }

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

        if directory and not directory.endswith("/"):
            directory += "/"
        result = []
        paginator = self.s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=directory)

        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    result.append(obj["Key"])
        return result

    def process_file(self, path: str, processor_func: Callable, **kwargs):
        """
        Process a file using the provided processor function.

        Args:
            path: Path to the file
            processor_func: Function that processes the file
            **kwargs: Additional arguments to pass to the processor function

        Returns:
            The result of the processor function
        """
        import logging
        import tempfile

        if not self.file_exists(path):
            raise FileNotFoundError(f"File not found in S3: {path}")
        with tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(path)[1], delete=True
        ) as temp_file:
            try:
                # Download the file from S3 to the temporary file

                self.s3.download_fileobj(self.bucket_name, path, temp_file)
                temp_file.flush()

                return processor_func(local_path=temp_file.name, **kwargs)
            except Exception as e:
                logging.error(f"Error processing S3 file {path}: {e}", exc_info=True)
                raise

    def is_directory(self, path: str) -> bool:
        """
        Check if a path is a directory in S3 storage.

        In S3, directories are virtual concepts. A path is considered a directory
        if there are objects with the path as a prefix.

        Args:
            path: Path to check

        Returns:
            bool: True if the path is a directory, False otherwise
        """
        # Ensure path ends with a slash if not empty
        if path and not path.endswith('/'):
            path += '/'

        response = self.s3.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=path,
            MaxKeys=1
        )

        return 'Contents' in response

    def remove_directory(self, directory: str) -> bool:
        """
        Remove a directory and all its contents from S3 storage.

        In S3, this removes all objects with the directory path as a prefix.
        Since S3 doesn't have actual directories, this effectively removes
        all files within the virtual directory structure.

        Args:
            directory: Directory path to remove

        Returns:
            bool: True if removal was successful, False otherwise
        """
        # Ensure directory ends with a slash if not empty
        if directory and not directory.endswith('/'):
            directory += '/'

        try:
            # Get all objects with the directory prefix
            objects_to_delete = []
            paginator = self.s3.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=directory)

            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        objects_to_delete.append({'Key': obj['Key']})

            if not objects_to_delete:
                return False

            batch_size = 1000
            for i in range(0, len(objects_to_delete), batch_size):
                batch = objects_to_delete[i:i + batch_size]

                response = self.s3.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': batch}
                )

                if 'Errors' in response and response['Errors']:
                    return False

            return True

        except ClientError:
            return False
