import json
import logging
import os
import tempfile
import mimetypes
from typing import List, Optional
from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    boto3 = None

logger = logging.getLogger(__name__)


class S3Loader(BaseRemote):
    """Load documents from an AWS S3 bucket."""

    def __init__(self):
        if boto3 is None:
            raise ImportError(
                "boto3 is required for S3Loader. Install it with: pip install boto3"
            )
        self.s3_client = None

    def _normalize_endpoint_url(self, endpoint_url: str, bucket: str) -> tuple[str, str]:
        """
        Normalize endpoint URL for S3-compatible services.

        Detects common mistakes like using bucket-prefixed URLs and extracts
        the correct endpoint and bucket name.

        Args:
            endpoint_url: The provided endpoint URL
            bucket: The provided bucket name

        Returns:
            Tuple of (normalized_endpoint_url, bucket_name)
        """
        import re
        from urllib.parse import urlparse

        if not endpoint_url:
            return endpoint_url, bucket

        parsed = urlparse(endpoint_url)
        host = parsed.netloc or parsed.path

        # Check for DigitalOcean Spaces bucket-prefixed URL pattern
        # e.g., https://mybucket.nyc3.digitaloceanspaces.com
        do_match = re.match(r"^([^.]+)\.([a-z0-9]+)\.digitaloceanspaces\.com$", host)
        if do_match:
            extracted_bucket = do_match.group(1)
            region = do_match.group(2)
            correct_endpoint = f"https://{region}.digitaloceanspaces.com"
            logger.warning(
                f"Detected bucket-prefixed DigitalOcean Spaces URL. "
                f"Extracted bucket '{extracted_bucket}' from endpoint. "
                f"Using endpoint: {correct_endpoint}"
            )
            # If bucket wasn't provided or differs, use extracted one
            if not bucket or bucket != extracted_bucket:
                logger.info(f"Using extracted bucket name: '{extracted_bucket}' (was: '{bucket}')")
                bucket = extracted_bucket
            return correct_endpoint, bucket

        # Check for just "digitaloceanspaces.com" without region
        if host == "digitaloceanspaces.com":
            logger.error(
                "Invalid DigitalOcean Spaces endpoint: missing region. "
                "Use format: https://<region>.digitaloceanspaces.com (e.g., https://lon1.digitaloceanspaces.com)"
            )

        return endpoint_url, bucket

    def _init_client(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = "us-east-1",
        endpoint_url: Optional[str] = None,
        bucket: Optional[str] = None,
    ) -> Optional[str]:
        """
        Initialize the S3 client with credentials.

        Returns:
            The potentially corrected bucket name if endpoint URL was normalized
        """
        from botocore.config import Config

        client_kwargs = {
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "region_name": region_name,
        }

        logger.info(f"Initializing S3 client with region: {region_name}")

        corrected_bucket = bucket
        if endpoint_url:
            # Normalize the endpoint URL and potentially extract bucket name
            normalized_endpoint, corrected_bucket = self._normalize_endpoint_url(endpoint_url, bucket)
            logger.info(f"Original endpoint URL: {endpoint_url}")
            logger.info(f"Normalized endpoint URL: {normalized_endpoint}")
            logger.info(f"Bucket name: '{corrected_bucket}'")

            client_kwargs["endpoint_url"] = normalized_endpoint
            # Use path-style addressing for S3-compatible services
            # (DigitalOcean Spaces, MinIO, etc.)
            client_kwargs["config"] = Config(s3={"addressing_style": "path"})
        else:
            logger.info("Using default AWS S3 endpoint")

        self.s3_client = boto3.client("s3", **client_kwargs)
        logger.info("S3 client initialized successfully")

        return corrected_bucket

    def is_text_file(self, file_path: str) -> bool:
        """Determine if a file is a text file based on extension."""
        text_extensions = {
            ".txt",
            ".md",
            ".markdown",
            ".rst",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".cs",
            ".go",
            ".rs",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".scala",
            ".html",
            ".css",
            ".scss",
            ".sass",
            ".less",
            ".sh",
            ".bash",
            ".zsh",
            ".fish",
            ".sql",
            ".r",
            ".m",
            ".mat",
            ".ini",
            ".cfg",
            ".conf",
            ".config",
            ".env",
            ".gitignore",
            ".dockerignore",
            ".editorconfig",
            ".log",
            ".csv",
            ".tsv",
        }

        file_lower = file_path.lower()
        for ext in text_extensions:
            if file_lower.endswith(ext):
                return True

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and (
            mime_type.startswith("text")
            or mime_type in ["application/json", "application/xml"]
        ):
            return True

        return False

    def is_supported_document(self, file_path: str) -> bool:
        """Check if file is a supported document type for parsing."""
        document_extensions = {
            ".pdf",
            ".docx",
            ".doc",
            ".xlsx",
            ".xls",
            ".pptx",
            ".ppt",
            ".epub",
            ".odt",
            ".rtf",
        }

        file_lower = file_path.lower()
        for ext in document_extensions:
            if file_lower.endswith(ext):
                return True

        return False

    def list_objects(self, bucket: str, prefix: str = "") -> List[str]:
        """
        List all objects in the bucket with the given prefix.

        Args:
            bucket: S3 bucket name
            prefix: Optional path prefix to filter objects

        Returns:
            List of object keys
        """
        objects = []
        paginator = self.s3_client.get_paginator("list_objects_v2")

        logger.info(f"Listing objects in bucket: '{bucket}' with prefix: '{prefix}'")
        logger.debug(f"S3 client endpoint: {self.s3_client.meta.endpoint_url}")

        try:
            page_count = 0
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                page_count += 1
                logger.debug(f"Processing page {page_count}, keys in response: {list(page.keys())}")
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        if not key.endswith("/"):
                            objects.append(key)
                            logger.debug(f"Found object: {key}")
                else:
                    logger.info(f"Page {page_count} has no 'Contents' key - bucket may be empty or prefix not found")

            logger.info(f"Found {len(objects)} objects in bucket '{bucket}'")

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            error_message = e.response.get("Error", {}).get("Message", "")
            logger.error(f"ClientError listing objects - Code: {error_code}, Message: {error_message}")
            logger.error(f"Full error response: {e.response}")
            logger.error(f"Bucket: '{bucket}', Prefix: '{prefix}', Endpoint: {self.s3_client.meta.endpoint_url}")

            if error_code == "NoSuchBucket":
                raise Exception(f"S3 bucket '{bucket}' does not exist")
            elif error_code == "AccessDenied":
                raise Exception(
                    f"Access denied to S3 bucket '{bucket}'. Check your credentials and permissions."
                )
            elif error_code == "NoSuchKey":
                # This is unusual for ListObjectsV2 - may indicate endpoint/bucket configuration issue
                logger.error(
                    "NoSuchKey error on ListObjectsV2 - this may indicate the bucket name "
                    "is incorrect or the endpoint URL format is wrong. "
                    "For DigitalOcean Spaces, the endpoint should be like: "
                    "https://<region>.digitaloceanspaces.com and bucket should be just the space name."
                )
                raise Exception(
                    f"S3 error: {e}. For S3-compatible services, verify: "
                    f"1) Endpoint URL format (e.g., https://nyc3.digitaloceanspaces.com), "
                    f"2) Bucket name is just the space/bucket name without region prefix"
                )
            else:
                raise Exception(f"S3 error: {e}")
        except NoCredentialsError:
            raise Exception(
                "AWS credentials not found. Please provide valid credentials."
            )

        return objects

    def get_object_content(self, bucket: str, key: str) -> Optional[str]:
        """
        Get the content of an S3 object as text.

        Args:
            bucket: S3 bucket name
            key: Object key

        Returns:
            File content as string, or None if file should be skipped
        """
        if not self.is_text_file(key) and not self.is_supported_document(key):
            return None

        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read()

            if self.is_text_file(key):
                try:
                    decoded_content = content.decode("utf-8").strip()
                    if not decoded_content:
                        return None
                    return decoded_content
                except UnicodeDecodeError:
                    return None
            elif self.is_supported_document(key):
                return self._process_document(content, key)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                return None
            elif error_code == "AccessDenied":
                print(f"Access denied to object: {key}")
                return None
            else:
                print(f"Error fetching object {key}: {e}")
                return None

        return None

    def _process_document(self, content: bytes, key: str) -> Optional[str]:
        """
        Process a document file (PDF, DOCX, etc.) and extract text.

        Args:
            content: File content as bytes
            key: Object key (filename)

        Returns:
            Extracted text content
        """
        ext = os.path.splitext(key)[1].lower()

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        try:
            from application.parser.file.bulk import SimpleDirectoryReader

            reader = SimpleDirectoryReader(input_files=[tmp_path])
            documents = reader.load_data()
            if documents:
                return "\n\n".join(doc.text for doc in documents if doc.text)
            return None
        except Exception as e:
            print(f"Error processing document {key}: {e}")
            return None
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def load_data(self, inputs) -> List[Document]:
        """
        Load documents from an S3 bucket.

        Args:
            inputs: JSON string or dict containing:
                - aws_access_key_id: AWS access key ID
                - aws_secret_access_key: AWS secret access key
                - bucket: S3 bucket name
                - prefix: Optional path prefix to filter objects
                - region: AWS region (default: us-east-1)
                - endpoint_url: Custom S3 endpoint URL (for MinIO, R2, etc.)

        Returns:
            List of Document objects
        """
        if isinstance(inputs, str):
            try:
                data = json.loads(inputs)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON input: {e}")
        else:
            data = inputs

        required_fields = ["aws_access_key_id", "aws_secret_access_key", "bucket"]
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        aws_access_key_id = data["aws_access_key_id"]
        aws_secret_access_key = data["aws_secret_access_key"]
        bucket = data["bucket"]
        prefix = data.get("prefix", "")
        region = data.get("region", "us-east-1")
        endpoint_url = data.get("endpoint_url", "")

        logger.info(f"Loading data from S3 - Bucket: '{bucket}', Prefix: '{prefix}', Region: '{region}'")
        if endpoint_url:
            logger.info(f"Custom endpoint URL provided: '{endpoint_url}'")

        corrected_bucket = self._init_client(
            aws_access_key_id, aws_secret_access_key, region, endpoint_url or None, bucket
        )

        # Use the corrected bucket name if endpoint URL normalization extracted one
        if corrected_bucket and corrected_bucket != bucket:
            logger.info(f"Using corrected bucket name: '{corrected_bucket}' (original: '{bucket}')")
            bucket = corrected_bucket

        objects = self.list_objects(bucket, prefix)
        documents = []

        for key in objects:
            content = self.get_object_content(bucket, key)
            if content is None:
                continue

            documents.append(
                Document(
                    text=content,
                    doc_id=key,
                    extra_info={
                        "title": os.path.basename(key),
                        "source": f"s3://{bucket}/{key}",
                        "bucket": bucket,
                        "key": key,
                    },
                )
            )

        logger.info(f"Loaded {len(documents)} documents from S3 bucket '{bucket}'")
        return documents
