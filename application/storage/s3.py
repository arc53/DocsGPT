"""S3 storage implementation."""

import io
import logging
import os
import posixpath
from typing import BinaryIO, Callable, List, Optional, Tuple

import boto3
from application.core.settings import settings

from application.storage.base import BaseStorage
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Storage(BaseStorage):
    """S3-compatible object storage (AWS S3, MinIO, Cloudflare R2, etc.)."""

    @staticmethod
    def _resolve_credentials() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolve S3 credentials, falling back to deprecated SAGEMAKER_* vars.

        Returns:
            Tuple of (access_key_id, secret_access_key, region).
        """
        access_key = settings.S3_ACCESS_KEY_ID
        secret_key = settings.S3_SECRET_ACCESS_KEY
        region = settings.S3_REGION

        legacy_access = getattr(settings, "SAGEMAKER_ACCESS_KEY", None)
        legacy_secret = getattr(settings, "SAGEMAKER_SECRET_KEY", None)
        legacy_region = getattr(settings, "SAGEMAKER_REGION", None)

        used_legacy = (
            (not access_key and legacy_access)
            or (not secret_key and legacy_secret)
            or (not region and legacy_region)
        )
        if used_legacy:
            logger.warning(
                "Using SAGEMAKER_* credentials for S3 storage is deprecated; "
                "set S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, and S3_REGION instead."
            )

        return (
            access_key or legacy_access,
            secret_key or legacy_secret,
            region or legacy_region,
        )

    @staticmethod
    def _validate_path(path: str) -> str:
        """Validate and normalize an S3 key to prevent path traversal.

        Raises:
            ValueError: If the path contains traversal sequences or is absolute.
        """
        if "\x00" in path:
            raise ValueError(f"Null byte in path: {path}")
        normalized = posixpath.normpath(path)
        if normalized.startswith("/") or normalized.startswith(".."):
            raise ValueError(f"Path traversal detected: {path}")
        return normalized

    def __init__(self, bucket_name=None):
        """
        Initialize S3 storage.

        Args:
            bucket_name: S3 bucket name (optional, defaults to settings)
        """
        self.bucket_name = bucket_name or settings.S3_BUCKET_NAME

        aws_access_key_id, aws_secret_access_key, region_name = self._resolve_credentials()
        self.region = region_name

        client_kwargs = {
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "region_name": region_name,
        }
        # Custom endpoint for S3-compatible services (MinIO, R2, B2, Spaces, ...).
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        # Most non-AWS services require path-style addressing.
        if settings.S3_PATH_STYLE:
            client_kwargs["config"] = Config(s3={"addressing_style": "path"})

        self.s3 = boto3.client("s3", **client_kwargs)

    def save_file(
        self,
        file_data: BinaryIO,
        path: str,
        storage_class: str = "INTELLIGENT_TIERING",
        **kwargs,
    ) -> dict:
        """Save a file to S3 storage."""
        path = self._validate_path(path)
        self.s3.upload_fileobj(
            file_data, self.bucket_name, path, ExtraArgs={"StorageClass": storage_class}
        )

        return {
            "storage_type": "s3",
            "bucket_name": self.bucket_name,
            "uri": f"s3://{self.bucket_name}/{path}",
            "region": self.region,
        }

    def get_file(self, path: str) -> BinaryIO:
        """Get a file from S3 storage."""
        path = self._validate_path(path)
        if not self.file_exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        file_obj = io.BytesIO()
        self.s3.download_fileobj(self.bucket_name, path, file_obj)
        file_obj.seek(0)
        return file_obj

    def generate_presigned_url(self, path: str, expires_in: int = 300) -> str:
        """Return a short-lived presigned GET URL for a private object (TTL <= 1h)."""
        path = self._validate_path(path)
        expires_in = min(expires_in, 3600)
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": path},
            ExpiresIn=expires_in,
        )

    def delete_file(self, path: str) -> bool:
        """Delete a file from S3 storage."""
        path = self._validate_path(path)
        try:
            self.s3.delete_object(Bucket=self.bucket_name, Key=path)
            return True
        except ClientError:
            return False

    def file_exists(self, path: str) -> bool:
        """Check if a file exists in S3 storage."""
        path = self._validate_path(path)
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

        path = self._validate_path(path)
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
