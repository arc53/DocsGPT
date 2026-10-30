import json
import logging
from functools import partial
from typing import Any, Dict, List, Union

from docsgpt.parser.remote.website_loader import WebsiteLoader, parse_website_config
from docsgpt.parser.remote.website_tree import config_from_legacy
from docsgpt.parser.remote.reddit_loader import RedditPostsLoaderRemote
from docsgpt.parser.remote.github_loader import GitHubLoader
from docsgpt.parser.remote.linear_loader import LinearLoader
from docsgpt.parser.remote.s3_loader import S3Loader
from docsgpt.parser.schema.base import Document

logger = logging.getLogger(__name__)

# The old web loaders' types: their sources load as the Website config they convert to.
LEGACY_WEB_TYPES = ("url", "crawler", "sitemap")


class LegacyWebsiteLoader(WebsiteLoader):
    """A url, crawler or sitemap source, loaded as its Website config (``config_from_legacy``)."""

    def __init__(self, source_type: str) -> None:
        """
        Args:
            source_type: The source's legacy type, which says how its address converts.
        """
        super().__init__()
        self.source_type = source_type

    def load_data(self, inputs: Union[str, List[str], Dict[str, Any]]) -> List[Document]:
        """Convert the input and run the Website load on it.

        Args:
            inputs: What a sync hands over (the converted config, from
                ``normalize_remote_data``) or an upload does (the address).

        Returns:
            The pages, as ``WebsiteLoader.load_data``; none when the input
            holds no web address.
        """
        config = config_from_legacy(self.source_type, inputs)
        if config is None:
            logger.warning(f"A {self.source_type} source has no web address to load")
            self.report = {"pages": 0, "sites": [], "limit_reached": False}
            return []
        return super().load_data(config)


class RemoteCreator:
    """
    Factory class for creating remote content loaders.

    These loaders fetch content from remote web sources like URLs,
    sitemaps, web crawlers, social media platforms, etc.

    For external knowledge base connectors (like Google Drive),
    use ConnectorCreator instead.
    """

    loaders = {
        "website": WebsiteLoader,
        **{source_type: partial(LegacyWebsiteLoader, source_type) for source_type in LEGACY_WEB_TYPES},
        "reddit": RedditPostsLoaderRemote,
        "github": GitHubLoader,
        "s3": S3Loader,
        "linear": LinearLoader,
    }

    @classmethod
    def create_loader(cls, type, *args, **kwargs):
        loader_class = cls.loaders.get(type.lower())
        if not loader_class:
            raise ValueError(f"No loader class found for type {type}")
        return loader_class(*args, **kwargs)


# Keys a github remote_data dict may hold its URL under (``raw`` is the legacy shape).
_URL_DATA_KEYS = ("url", "urls", "repo_url", "raw")


def normalize_remote_data(source_type, remote_data):
    """Convert a stored ``sources.remote_data`` JSONB value into the
    ``source_data`` shape the matching loader expects.

    Args:
        source_type: The ``sources.type`` value (the loader name).
        remote_data: The stored ``remote_data`` (dict, list, str, or None).

    Returns:
        Loader input: the validated Website config for website, url,
        crawler and sitemap (the last three converted, ``config_from_legacy``),
        a URL string for github, a JSON string for reddit, a dict for s3;
        ``None`` when the row has nothing syncable.
    """
    if remote_data is None:
        return None

    # Some legacy rows stored the JSON itself as a string.
    if isinstance(remote_data, str):
        stripped = remote_data.strip()
        if stripped[:1] in ("{", "["):
            try:
                remote_data = json.loads(stripped)
            except json.JSONDecodeError:
                # Not actually JSON — leave remote_data as the original
                # string; the per-loader branches below handle a string.
                pass

    loader = (source_type or "").lower()

    if loader == "website":
        # A stored config is read leniently: a lowered WEB_MAX_PAGES must not stop its syncs.
        try:
            return parse_website_config(remote_data, enforce_page_cap=False)
        except ValueError:
            return None

    if loader in LEGACY_WEB_TYPES:
        return config_from_legacy(loader, remote_data)

    if loader == "github":
        if isinstance(remote_data, dict):
            for key in _URL_DATA_KEYS:
                value = remote_data.get(key)
                if value:
                    return value
            # No URL key — None keeps the loader off the dict-crash path.
            return None
        return remote_data

    if loader == "reddit":
        # reddit's loader runs json.loads() on its input — needs a string.
        if isinstance(remote_data, (dict, list)):
            return json.dumps(remote_data)
        return remote_data

    # s3's and linear's loaders accept a dict or JSON string; pass it through unchanged.
    return remote_data
