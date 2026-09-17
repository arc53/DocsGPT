"""Where uploaded files and generated artifacts are stored."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


class StorageSettings(SettingsGroup):
    """Local disk or an S3-compatible bucket, and how download URLs are produced."""

    STORAGE_TYPE: Literal["local", "s3"] = Field(default="local", description="File storage backend.")
    URL_STRATEGY: Literal["backend", "s3"] = Field(
        default="backend",
        description="How download links are produced: backend (streamed through the API) or s3 (presigned URLs).",
    )

    # S3-compatible object storage (STORAGE_TYPE=s3): AWS S3, MinIO, R2, B2, Spaces, ...
    # For non-AWS, set S3_ENDPOINT_URL and usually S3_PATH_STYLE=true.
    S3_BUCKET_NAME: str = Field(default="docsgpt-test-bucket", description="Bucket name.")
    S3_ENDPOINT_URL: Optional[str] = Field(
        default=None, description="Custom endpoint for S3-compatible services (MinIO, R2, B2, Spaces); omit for AWS."
    )
    S3_ACCESS_KEY_ID: Optional[str] = Field(default=None, description="Access key id.")
    S3_SECRET_ACCESS_KEY: Optional[str] = Field(default=None, description="Secret access key.")
    S3_REGION: Optional[str] = Field(default=None, description='AWS region; use "auto" for Cloudflare R2.')
    S3_PATH_STYLE: bool = Field(
        default=False, description="Path-style addressing (required by most non-AWS services)."
    )

    # Legacy AWS credentials from the retired SageMaker provider.
    SAGEMAKER_REGION: Optional[str] = Field(
        default=None,
        description="Legacy AWS region from the retired SageMaker provider; deprecated fallback for S3_REGION.",
    )
    SAGEMAKER_ACCESS_KEY: Optional[str] = Field(
        default=None,
        description="Legacy AWS access key from the retired SageMaker provider; deprecated fallback for S3_ACCESS_KEY_ID.",
    )
    SAGEMAKER_SECRET_KEY: Optional[str] = Field(
        default=None,
        description=(
            "Legacy AWS secret key from the retired SageMaker provider; deprecated fallback for "
            "S3_SECRET_ACCESS_KEY."
        ),
    )

    @field_validator("STORAGE_TYPE", "URL_STRATEGY", mode="before")
    @classmethod
    def _normalize_storage_choices(cls, v):
        return normalize_choice(v)
