import base64
import json
import logging
from enum import Enum
from typing import Any, Dict, Optional, Union
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """Supported content types for request bodies."""

    JSON = "application/json"
    FORM_URLENCODED = "application/x-www-form-urlencoded"
    MULTIPART_FORM_DATA = "multipart/form-data"
    TEXT_PLAIN = "text/plain"
    XML = "application/xml"
    OCTET_STREAM = "application/octet-stream"


class RequestBodySerializer:
    """Serializes request bodies according to content-type and OpenAPI 3.1 spec."""

    @staticmethod
    def serialize(
        body_data: Dict[str, Any],
        content_type: str = ContentType.JSON,
        encoding_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[Union[str, bytes], Dict[str, str]]:
        """
        Serialize body data to appropriate format.

        Args:
            body_data: Dictionary of body parameters
            content_type: Content-Type header value
            encoding_rules: OpenAPI Encoding Object rules per field

        Returns:
            Tuple of (serialized_body, updated_headers_dict)

        Raises:
            ValueError: If serialization fails
        """
        if not body_data:
            return None, {}

        try:
            content_type_lower = content_type.lower().split(";")[0].strip()

            if content_type_lower == ContentType.JSON:
                return RequestBodySerializer._serialize_json(body_data)

            elif content_type_lower == ContentType.FORM_URLENCODED:
                return RequestBodySerializer._serialize_form_urlencoded(
                    body_data, encoding_rules
                )

            elif content_type_lower == ContentType.MULTIPART_FORM_DATA:
                return RequestBodySerializer._serialize_multipart_form_data(
                    body_data, encoding_rules
                )

            elif content_type_lower == ContentType.TEXT_PLAIN:
                return RequestBodySerializer._serialize_text_plain(body_data)

            elif content_type_lower == ContentType.XML:
                return RequestBodySerializer._serialize_xml(body_data)

            elif content_type_lower == ContentType.OCTET_STREAM:
                return RequestBodySerializer._serialize_octet_stream(body_data)

            else:
                logger.warning(
                    f"Unknown content type: {content_type}, treating as JSON"
                )
                return RequestBodySerializer._serialize_json(body_data)

        except Exception as e:
            logger.error(f"Error serializing body: {str(e)}", exc_info=True)
            raise ValueError(f"Failed to serialize request body: {str(e)}")

    @staticmethod
    def _serialize_json(body_data: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
        """Serialize body as JSON per OpenAPI spec."""
        try:
            serialized = json.dumps(
                body_data, separators=(",", ":"), ensure_ascii=False
            )
            headers = {"Content-Type": ContentType.JSON.value}
            return serialized, headers
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize JSON body: {str(e)}")

    @staticmethod
    def _serialize_form_urlencoded(
        body_data: Dict[str, Any],
        encoding_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[str, Dict[str, str]]:
        """Serialize body as application/x-www-form-urlencoded per RFC1866/RFC3986."""
        encoding_rules = encoding_rules or {}
        params = []

        for key, value in body_data.items():
            if value is None:
                continue

            rule = encoding_rules.get(key, {})
            style = rule.get("style", "form")
            explode = rule.get("explode", style == "form")
            content_type = rule.get("contentType", "text/plain")

            serialized_value = RequestBodySerializer._serialize_form_value(
                value, style, explode, content_type, key
            )

            if isinstance(serialized_value, list):
                for sv in serialized_value:
                    params.append((key, sv))
            else:
                params.append((key, serialized_value))

        # Use standard urlencode (replaces space with +)
        serialized = urlencode(params, safe="")
        headers = {"Content-Type": ContentType.FORM_URLENCODED.value}
        return serialized, headers

    @staticmethod
    def _serialize_form_value(
        value: Any, style: str, explode: bool, content_type: str, key: str
    ) -> Union[str, list]:
        """Serialize individual form value with encoding rules."""
        if isinstance(value, dict):
            if content_type == "application/json":
                return json.dumps(value, separators=(",", ":"))
            elif content_type == "application/xml":
                return RequestBodySerializer._dict_to_xml(value)
            else:
                if style == "deepObject" and explode:
                    return [
                        f"{RequestBodySerializer._percent_encode(str(v))}"
                        for v in value.values()
                    ]
                elif explode:
                    return [
                        f"{RequestBodySerializer._percent_encode(str(v))}"
                        for v in value.values()
                    ]
                else:
                    pairs = [f"{k},{v}" for k, v in value.items()]
                    return RequestBodySerializer._percent_encode(",".join(pairs))

        elif isinstance(value, (list, tuple)):
            if explode:
                return [
                    RequestBodySerializer._percent_encode(str(item)) for item in value
                ]
            else:
                return RequestBodySerializer._percent_encode(
                    ",".join(str(v) for v in value)
                )

        else:
            return RequestBodySerializer._percent_encode(str(value))

    @staticmethod
    def _serialize_multipart_form_data(
        body_data: Dict[str, Any],
        encoding_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> tuple[bytes, Dict[str, str]]:
        """
        Serialize body as multipart/form-data per RFC7578.

        Supports file uploads and encoding rules.
        """
        import secrets

        encoding_rules = encoding_rules or {}
        boundary = f"----DocsGPT{secrets.token_hex(16)}"
        parts = []

        for key, value in body_data.items():
            if value is None:
                continue

            rule = encoding_rules.get(key, {})
            content_type = rule.get("contentType", "text/plain")
            headers_rule = rule.get("headers", {})

            part = RequestBodySerializer._create_multipart_part(
                key, value, content_type, headers_rule
            )
            parts.append(part)

        body_bytes = f"--{boundary}\r\n".encode("utf-8")
        body_bytes += f"--{boundary}\r\n".join(parts).encode("utf-8")
        body_bytes += f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        return body_bytes, headers

    @staticmethod
    def _create_multipart_part(
        name: str, value: Any, content_type: str, headers_rule: Dict[str, Any]
    ) -> str:
        """Create a single multipart/form-data part."""
        headers = [
            f'Content-Disposition: form-data; name="{RequestBodySerializer._percent_encode(name)}"'
        ]

        if isinstance(value, bytes):
            if content_type == "application/octet-stream":
                value_encoded = base64.b64encode(value).decode("utf-8")
            else:
                value_encoded = value.decode("utf-8", errors="replace")
            headers.append(f"Content-Type: {content_type}")
            headers.append("Content-Transfer-Encoding: base64")
        elif isinstance(value, dict):
            if content_type == "application/json":
                value_encoded = json.dumps(value, separators=(",", ":"))
            elif content_type == "application/xml":
                value_encoded = RequestBodySerializer._dict_to_xml(value)
            else:
                value_encoded = str(value)
            headers.append(f"Content-Type: {content_type}")
        elif isinstance(value, str) and content_type != "text/plain":
            try:
                if content_type == "application/json":
                    json.loads(value)
                    value_encoded = value
                elif content_type == "application/xml":
                    value_encoded = value
                else:
                    value_encoded = str(value)
            except json.JSONDecodeError:
                value_encoded = str(value)
            headers.append(f"Content-Type: {content_type}")
        else:
            value_encoded = str(value)
            if content_type != "text/plain":
                headers.append(f"Content-Type: {content_type}")

        part = "\r\n".join(headers) + "\r\n\r\n" + value_encoded + "\r\n"
        return part

    @staticmethod
    def _serialize_text_plain(body_data: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
        """Serialize body as plain text."""
        if len(body_data) == 1:
            value = list(body_data.values())[0]
            return str(value), {"Content-Type": ContentType.TEXT_PLAIN.value}
        else:
            text = "\n".join(f"{k}: {v}" for k, v in body_data.items())
            return text, {"Content-Type": ContentType.TEXT_PLAIN.value}

    @staticmethod
    def _serialize_xml(body_data: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
        """Serialize body as XML."""
        xml_str = RequestBodySerializer._dict_to_xml(body_data)
        return xml_str, {"Content-Type": ContentType.XML.value}

    @staticmethod
    def _serialize_octet_stream(
        body_data: Dict[str, Any],
    ) -> tuple[bytes, Dict[str, str]]:
        """Serialize body as binary octet stream."""
        if isinstance(body_data, bytes):
            return body_data, {"Content-Type": ContentType.OCTET_STREAM.value}
        elif isinstance(body_data, str):
            return body_data.encode("utf-8"), {
                "Content-Type": ContentType.OCTET_STREAM.value
            }
        else:
            serialized = json.dumps(body_data)
            return serialized.encode("utf-8"), {
                "Content-Type": ContentType.OCTET_STREAM.value
            }

    @staticmethod
    def _percent_encode(value: str, safe_chars: str = "") -> str:
        """
        Percent-encode per RFC3986.

        Args:
            value: String to encode
            safe_chars: Additional characters to not encode
        """
        return quote(value, safe=safe_chars)

    @staticmethod
    def _dict_to_xml(data: Dict[str, Any], root_name: str = "root") -> str:
        """
        Convert dict to simple XML format.
        """

        def build_xml(obj: Any, name: str) -> str:
            if isinstance(obj, dict):
                inner = "".join(build_xml(v, k) for k, v in obj.items())
                return f"<{name}>{inner}</{name}>"
            elif isinstance(obj, (list, tuple)):
                items = "".join(
                    build_xml(item, f"{name[:-1] if name.endswith('s') else name}")
                    for item in obj
                )
                return items
            else:
                return f"<{name}>{RequestBodySerializer._escape_xml(str(obj))}</{name}>"

        root = build_xml(data, root_name)
        return f'<?xml version="1.0" encoding="UTF-8"?>{root}'

    @staticmethod
    def _escape_xml(value: str) -> str:
        """Escape XML special characters."""
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
