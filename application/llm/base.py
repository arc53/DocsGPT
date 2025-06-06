import logging
from abc import ABC, abstractmethod

from application.cache import gen_cache, stream_cache

from application.core.settings import settings
from application.usage import gen_token_usage, stream_token_usage

logger = logging.getLogger(__name__)


class BaseLLM(ABC):
    def __init__(
        self,
        decoded_token=None,
    ):
        self.decoded_token = decoded_token
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        self.fallback_provider = settings.FALLBACK_LLM_PROVIDER
        self.fallback_model_name = settings.FALLBACK_LLM_NAME
        self.fallback_llm_api_key = settings.FALLBACK_LLM_API_KEY
        self._fallback_llm = None

    @property
    def fallback_llm(self):
        """Lazy-loaded fallback LLM instance."""
        if (
            self._fallback_llm is None
            and self.fallback_provider
            and self.fallback_model_name
        ):
            try:
                from application.llm.llm_creator import LLMCreator

                self._fallback_llm = LLMCreator.create_llm(
                    self.fallback_provider,
                    self.fallback_llm_api_key,
                    None,
                    self.decoded_token,
                )
            except Exception as e:
                logger.error(
                    f"Failed to initialize fallback LLM: {str(e)}", exc_info=True
                )
        return self._fallback_llm

    def _execute_with_fallback(
        self, method_name: str, decorators: list, *args, **kwargs
    ):
        """
        Unified method execution with fallback support.

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

        try:
            return decorated_method()
        except Exception as e:
            if not self.fallback_llm:
                logger.error(f"Primary LLM failed and no fallback available: {str(e)}")
                raise
            logger.warning(
                f"Falling back to {self.fallback_provider}/{self.fallback_model_name}. Error: {str(e)}"
            )

            fallback_method = getattr(
                self.fallback_llm, method_name.replace("_raw_", "")
            )
            return fallback_method(*args, **kwargs)

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

    def gen_stream(self, model, messages, stream=True, tools=None, *args, **kwargs):
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

    def get_supported_attachment_types(self):
        """
        Return a list of MIME types supported by this LLM for file uploads.

        Returns:
            list: List of supported MIME types
        """
        return []  # Default: no attachments supported
