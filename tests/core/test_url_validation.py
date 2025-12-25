"""Tests for SSRF URL validation module."""

import pytest
from unittest.mock import patch

from application.core.url_validation import (
    SSRFError,
    validate_url,
    validate_url_safe,
    is_private_ip,
    is_metadata_ip,
)


class TestIsPrivateIP:
    """Tests for is_private_ip function."""

    def test_loopback_ipv4(self):
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    def test_private_class_a(self):
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_private_class_b(self):
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_private_class_c(self):
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_link_local(self):
        assert is_private_ip("169.254.0.1") is True

    def test_public_ip(self):
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("93.184.216.34") is False

    def test_invalid_ip(self):
        assert is_private_ip("not-an-ip") is False
        assert is_private_ip("") is False


class TestIsMetadataIP:
    """Tests for is_metadata_ip function."""

    def test_aws_metadata_ip(self):
        assert is_metadata_ip("169.254.169.254") is True

    def test_aws_ecs_metadata_ip(self):
        assert is_metadata_ip("169.254.170.2") is True

    def test_non_metadata_ip(self):
        assert is_metadata_ip("8.8.8.8") is False
        assert is_metadata_ip("10.0.0.1") is False


class TestValidateUrl:
    """Tests for validate_url function."""

    def test_adds_scheme_if_missing(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "93.184.216.34"  # Public IP
            result = validate_url("example.com")
            assert result == "http://example.com"

    def test_preserves_https_scheme(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "93.184.216.34"
            result = validate_url("https://example.com")
            assert result == "https://example.com"

    def test_blocks_localhost(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://localhost")
        assert "localhost" in str(exc_info.value).lower()

    def test_blocks_localhost_localdomain(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://localhost.localdomain")
        assert "not allowed" in str(exc_info.value).lower()

    def test_blocks_loopback_ip(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://127.0.0.1")
        assert "private" in str(exc_info.value).lower() or "internal" in str(exc_info.value).lower()

    def test_blocks_private_ip_class_a(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://10.0.0.1")
        assert "private" in str(exc_info.value).lower() or "internal" in str(exc_info.value).lower()

    def test_blocks_private_ip_class_b(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://172.16.0.1")
        assert "private" in str(exc_info.value).lower() or "internal" in str(exc_info.value).lower()

    def test_blocks_private_ip_class_c(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://192.168.1.1")
        assert "private" in str(exc_info.value).lower() or "internal" in str(exc_info.value).lower()

    def test_blocks_aws_metadata_ip(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://169.254.169.254")
        assert "metadata" in str(exc_info.value).lower()

    def test_blocks_aws_metadata_with_path(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://169.254.169.254/latest/meta-data/")
        assert "metadata" in str(exc_info.value).lower()

    def test_blocks_gcp_metadata_hostname(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://metadata.google.internal")
        assert "not allowed" in str(exc_info.value).lower()

    def test_blocks_ftp_scheme(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("ftp://example.com")
        assert "scheme" in str(exc_info.value).lower()

    def test_blocks_file_scheme(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("file:///etc/passwd")
        assert "scheme" in str(exc_info.value).lower()

    def test_blocks_hostname_resolving_to_private_ip(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "192.168.1.1"
            with pytest.raises(SSRFError) as exc_info:
                validate_url("http://internal.example.com")
            assert "private" in str(exc_info.value).lower() or "internal" in str(exc_info.value).lower()

    def test_blocks_hostname_resolving_to_metadata_ip(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "169.254.169.254"
            with pytest.raises(SSRFError) as exc_info:
                validate_url("http://evil.example.com")
            assert "metadata" in str(exc_info.value).lower()

    def test_allows_public_ip(self):
        result = validate_url("http://8.8.8.8")
        assert result == "http://8.8.8.8"

    def test_allows_public_hostname(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "93.184.216.34"
            result = validate_url("https://example.com")
            assert result == "https://example.com"

    def test_raises_on_unresolvable_hostname(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(SSRFError) as exc_info:
                validate_url("http://nonexistent.invalid")
            assert "resolve" in str(exc_info.value).lower()

    def test_raises_on_empty_hostname(self):
        with pytest.raises(SSRFError) as exc_info:
            validate_url("http://")
        assert "hostname" in str(exc_info.value).lower()

    def test_allow_localhost_flag(self):
        # Should work with allow_localhost=True
        result = validate_url("http://localhost", allow_localhost=True)
        assert result == "http://localhost"

        result = validate_url("http://127.0.0.1", allow_localhost=True)
        assert result == "http://127.0.0.1"


class TestValidateUrlSafe:
    """Tests for validate_url_safe non-throwing function."""

    def test_returns_tuple_on_success(self):
        with patch("application.core.url_validation.resolve_hostname") as mock_resolve:
            mock_resolve.return_value = "93.184.216.34"
            is_valid, url, error = validate_url_safe("https://example.com")
            assert is_valid is True
            assert url == "https://example.com"
            assert error is None

    def test_returns_tuple_on_failure(self):
        is_valid, url, error = validate_url_safe("http://localhost")
        assert is_valid is False
        assert url == "http://localhost"
        assert error is not None
        assert "localhost" in error.lower()

    def test_returns_error_message_for_private_ip(self):
        is_valid, url, error = validate_url_safe("http://192.168.1.1")
        assert is_valid is False
        assert "private" in error.lower() or "internal" in error.lower()
