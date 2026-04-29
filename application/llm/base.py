import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from application.cache import gen_cache, stream_cache

from application.core.settings import settings
from application.usage import gen_token_usage, stream_token_usage

logger = logging.getLogger(__name__)


class BaseLLM(ABC):
    # Stamped onto the ``llm_stream_start`` event so dashboards can group
    # calls by vendor. Subclasses override.
    provider_name: ClassVar[str] = "unknown"

    def __init__(
        self,
        decoded_token=None,
        agent_id=None,
        model_id=None,
        base_url=None,
        backup_models=None,
        model_user_id=None,
        capabilities=None,
    ):
        self.decoded_token = decoded_token
        self.agent_id = str(agent_id) if agent_id else None
        self.model_id = model_id
        self.base_url = base_url
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        self._backup_models = backup_models or []
        self._fallback_llm = None
        # Registry-resolved per-model capability overrides (BYOM caps,
        # operator YAML). None falls back to provider-class defaults.
        self.capabilities = capabilities
        # BYOM-resolution scope captured at LLM creation time so backup
        # / fallback lookups hit the same per-user layer as the primary.
        self.model_user_id = model_user_id

    @property
    def fallback_llm(self):
        """Lazy-loaded fallback LLM: tries per-agent backup models first,
        then the global FALLBACK_* settings."""
        if self._fallback_llm is not None:
            return self._fallback_llm

        from application.llm.llm_creator import LLMCreator
        from application.core.model_utils import (
            get_provider_from_model_id,
            get_api_key_for_provider,
        )

        # model_user_id (BYOM scope) takes precedence over the caller's
        # sub so shared-agent backups resolve under the owner's layer.
        caller_sub = (
            self.decoded_token.get("sub")
            if isinstance(self.decoded_token, dict)
            else None
        )
        backup_user_id = self.model_user_id or caller_sub
        for backup_model_id in self._backup_models:
            try:
                provider = get_provider_from_model_id(
                    backup_model_id, user_id=backup_user_id
                )
                if not provider:
                    logger.warning(
                        f"Could not resolve provider for backup model: {backup_model_id}"
                    )
                    continue
                api_key = get_api_key_for_provider(provider)
                self._fallback_llm = LLMCreator.create_llm(
                    provider,
                    api_key=api_key,
                    user_api_key=getattr(self, "user_api_key", None),
                    decoded_token=self.decoded_token,
                    model_id=backup_model_id,
                    agent_id=self.agent_id,
                    model_user_id=self.model_user_id,
                )
                logger.info(
                    f"Fallback LLM initialized from agent backup model: "
                    f"{provider}/{backup_model_id}"
                )
                return self._fallback_llm
            except Exception as e:
                logger.warning(
                    f"Failed to initialize backup model {backup_model_id}: {str(e)}"
                )
                continue

        # Fall back to global FALLBACK_* settings. Forward
        # ``model_user_id`` here too: deployments can configure
        # ``FALLBACK_LLM_NAME`` to a BYOM UUID, and that UUID is owned
        # by the same user the primary model was resolved under.
        if settings.FALLBACK_LLM_PROVIDER:
            try:
                self._fallback_llm = LLMCreator.create_llm(
                    settings.FALLBACK_LLM_PROVIDER,
                    api_key=settings.FALLBACK_LLM_API_KEY or settings.API_KEY,
                    user_api_key=getattr(self, "user_api_key", None),
                    decoded_token=self.decoded_token,
                    model_id=settings.FALLBACK_LLM_NAME,
                    agent_id=self.agent_id,
                    model_user_id=self.model_user_id,
                )
                logger.info(
                    f"Fallback LLM initialized from global settings: "
                    f"{settings.FALLBACK_LLM_PROVIDER}/{settings.FALLBACK_LLM_NAME}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to initialize fallback LLM: {str(e)}", exc_info=True
                )

        return self._fallback_llm

    @staticmethod
    def _remove_null_values(args_dict):
        if not isinstance(args_dict, dict):
            return args_dict
        return {k: v for k, v in args_dict.items() if v is not None}

    @staticmethod
    def _is_non_retriable_client_error(exc: BaseException) -> bool:
        """4xx errors mean the request itself is malformed — retrying with
        a different model fails identically and doubles the work. Only
        transient/5xx/connection errors should trigger fallback."""
        try:
            from google.genai.errors import ClientError as _GenaiClientError

            if isinstance(exc, _GenaiClientError):
                return True
        except ImportError:
            pass
        for attr in ("status_code", "code", "http_status"):
            v = getattr(exc, attr, None)
            if isinstance(v, int) and 400 <= v < 500:
                return True
        resp = getattr(exc, "response", None)
        v = getattr(resp, "status_code", None)
        return isinstance(v, int) and 400 <= v < 500

    def _execute_with_fallback(
        self, method_name: str, decorators: list, *args, **kwargs
    ):
        """
        Execute method with fallback support.

        Args:
            method_name: Name of the raw method ('_raw_gen' or '_raw_gen_stream')
            decorators: List of decorators to apply
            *args: Positional arguments
            **kwargs: Keyword arguments
        """

        def decorated_method():
            method = getattr(self, method_name)
            for decorator in decorators:
                method = decorator(method)
            return method(self, *args, **kwargs)

        is_stream = "stream" in method_name

        if is_stream:
            return self._stream_with_fallback(
                decorated_method, method_name, decorators, *args, **kwargs
            )

        try:
            return decorated_method()
        except Exception as e:
            if self._is_non_retriable_client_error(e):
                logger.error(
                    f"Primary LLM failed with non-retriable client error; "
                    f"skipping fallback: {str(e)}"
                )
                raise
            if not self.fallback_llm:
                logger.error(f"Primary LLM failed and no fallback configured: {str(e)}")
                raise
            fallback = self.fallback_llm
            logger.warning(
                f"Primary LLM failed. Falling back to "
                f"{fallback.model_id}. Error: {str(e)}"
            )

            # Apply decorators to fallback's raw method directly — calling
            # fallback.gen() would re-enter the orchestrator and recurse via
            # fallback.fallback_llm.
            fallback_method = getattr(fallback, method_name)
            for decorator in decorators:
                fallback_method = decorator(fallback_method)
            fallback_kwargs = {**kwargs, "model": fallback.model_id}
            try:
                return fallback_method(fallback, *args, **fallback_kwargs)
            except Exception as e2:
                if self._is_non_retriable_client_error(e2):
                    logger.error(
                        f"Fallback LLM failed with non-retriable client "
                        f"error; giving up: {str(e2)}"
                    )
                else:
                    logger.error(f"Fallback LLM also failed; giving up: {str(e2)}")
                raise

    def _stream_with_fallback(
        self, decorated_method, method_name, decorators, *args, **kwargs
    ):
        """
        Wrapper generator that catches mid-stream errors and falls back.

        Unlike non-streaming calls where exceptions are raised immediately,
        streaming generators raise exceptions during iteration. This wrapper
        ensures that if the primary LLM fails at any point during streaming
        (creation or mid-stream), we fall back to the backup model.
        """
        try:
            yield from decorated_method()
        except Exception as e:
            if self._is_non_retriable_client_error(e):
                logger.error(
                    f"Primary LLM failed mid-stream with non-retriable client "
                    f"error; skipping fallback: {str(e)}"
                )
                raise
            if not self.fallback_llm:
                logger.error(
                    f"Primary LLM failed and no fallback configured: {str(e)}"
                )
                raise
            fallback = self.fallback_llm
            logger.warning(
                f"Primary LLM failed mid-stream. Falling back to "
                f"{fallback.model_id}. Error: {str(e)}"
            )
            # Apply decorators to fallback's raw stream method directly —
            # calling fallback.gen_stream() would re-enter the orchestrator
            # and recurse via fallback.fallback_llm. Emit the stream-start
            # event manually so dashboards still see the fallback's
            # provider/model when the response actually comes from it.
            fallback._emit_stream_start_log(
                fallback.model_id,
                kwargs.get("messages"),
                kwargs.get("tools"),
                bool(
                    kwargs.get("_usage_attachments")
                    or kwargs.get("attachments")
                ),
            )
            fallback_method = getattr(fallback, method_name)
            for decorator in decorators:
                fallback_method = decorator(fallback_method)
            fallback_kwargs = {**kwargs, "model": fallback.model_id}
            try:
                yield from fallback_method(fallback, *args, **fallback_kwargs)
            except Exception as e2:
                if self._is_non_retriable_client_error(e2):
                    logger.error(
                        f"Fallback LLM failed mid-stream with non-retriable "
                        f"client error; giving up: {str(e2)}"
                    )
                else:
                    logger.error(
                        f"Fallback LLM also failed mid-stream; giving up: {str(e2)}"
                    )
                raise

    def gen(self, model, messages, stream=False, tools=None, *args, **kwargs):
        decorators = [gen_token_usage, gen_cache]
        return self._execute_with_fallback(
            "_raw_gen",
            decorators,
            model=model,
            messages=messages,
            stream=stream,
            tools=tools,
            *args,
            **kwargs,
        )

    def _emit_stream_start_log(self, model, messages, tools, has_attachments):
        # Stamped with ``self.provider_name`` so dashboards can group calls
        # by vendor; the fallback path emits its own copy on the fallback
        # instance so the actual responding provider is recorded.
        logging.info(
            "llm_stream_start",
            extra={
                "model": model,
                "provider": self.provider_name,
                "message_count": len(messages) if messages is not None else 0,
                "has_attachments": bool(has_attachments),
                "has_tools": bool(tools),
            },
        )

    def _emit_stream_finished_log(
        self,
        model,
        *,
        prompt_tokens,
        completion_tokens,
        latency_ms,
        cached_tokens=None,
        error=None,
    ):
        # Paired with ``llm_stream_start`` so cost dashboards can sum tokens
        # by user/agent/provider. Token counts are client-side estimates
        # from ``stream_token_usage``; vendor-reported counts (incl.
        # ``cached_tokens`` for prompt caching) require per-provider
        # extraction in each ``_raw_gen_stream`` and aren't wired yet.
        extra = {
            "model": model,
            "provider": self.provider_name,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "latency_ms": int(latency_ms),
            "status": "error" if error is not None else "ok",
        }
        if cached_tokens is not None:
            extra["cached_tokens"] = int(cached_tokens)
        if error is not None:
            extra["error_class"] = type(error).__name__
        logging.info("llm_stream_finished", extra=extra)

    def gen_stream(self, model, messages, stream=True, tools=None, *args, **kwargs):
        # Attachments arrive as ``_usage_attachments`` from ``Agent._llm_gen``;
        # the ``stream_token_usage`` decorator pops that key, but the log
        # fires before the decorator runs so it's still in ``kwargs`` here.
        has_attachments = bool(
            kwargs.get("_usage_attachments") or kwargs.get("attachments")
        )
        self._emit_stream_start_log(model, messages, tools, has_attachments)
        decorators = [stream_cache, stream_token_usage]
        return self._execute_with_fallback(
            "_raw_gen_stream",
            decorators,
            model=model,
            messages=messages,
            stream=stream,
            tools=tools,
            *args,
            **kwargs,
        )

    @abstractmethod
    def _raw_gen(self, model, messages, stream, tools, *args, **kwargs):
        pass

    @abstractmethod
    def _raw_gen_stream(self, model, messages, stream, *args, **kwargs):
        pass

    def supports_tools(self):
        return hasattr(self, "_supports_tools") and callable(
            getattr(self, "_supports_tools")
        )

    def _supports_tools(self):
        raise NotImplementedError("Subclass must implement _supports_tools method")

    def supports_structured_output(self):
        """Check if the LLM supports structured output/JSON schema enforcement"""
        return hasattr(self, "_supports_structured_output") and callable(
            getattr(self, "_supports_structured_output")
        )

    def _supports_structured_output(self):
        return False

    def prepare_structured_output_format(self, json_schema):
        """Prepare structured output format specific to the LLM provider"""
        _ = json_schema
        return None

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by this LLM for file uploads.

        Returns:
            list: List of supported MIME types
        """
        return []
