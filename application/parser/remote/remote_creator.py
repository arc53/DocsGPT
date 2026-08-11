import json

from application.parser.remote.sitemap_loader import SitemapLoader
from application.parser.remote.crawler_loader import CrawlerLoader
from application.parser.remote.web_loader import WebLoader
from application.parser.remote.reddit_loader import RedditPostsLoaderRemote
from application.parser.remote.github_loader import GitHubLoader
from application.parser.remote.s3_loader import S3Loader


class RemoteCreator:
    """
    Factory class for creating remote content loaders.

    These loaders fetch content from remote web sources like URLs,
    sitemaps, web crawlers, social media platforms, etc.

    For external knowledge base connectors (like Google Drive),
    use ConnectorCreator instead.
    """

    loaders = {
        "url": WebLoader,
        "sitemap": SitemapLoader,
        "crawler": CrawlerLoader,
        "reddit": RedditPostsLoaderRemote,
        "github": GitHubLoader,
        "s3": S3Loader,
    }

    @classmethod
    def create_loader(cls, type, *args, **kwargs):
        loader_class = cls.loaders.get(type.lower())
        if not loader_class:
            raise ValueError(f"No loader class found for type {type}")
        return loader_class(*args, **kwargs)


# Loader types whose load_data expects a URL string, not a config dict.
_URL_LOADER_TYPES = {"url", "crawler", "sitemap", "github"}

# Keys a remote_data dict may hold the URL under (``raw`` is the legacy shape).
_URL_DATA_KEYS = ("url", "urls", "repo_url", "raw")


def normalize_remote_data(source_type, remote_data):
    """Convert a stored ``sources.remote_data`` JSONB value into the
    ``source_data`` shape the matching loader expects.

    Args:
        source_type: The ``sources.type`` value (the loader name).
        remote_data: The stored ``remote_data`` (dict, list, str, or None).

    Returns:
        Loader input: a URL string or list for url/crawler/sitemap/github,
        a JSON string for reddit, a dict for s3; ``None`` when the row has
        nothing syncable.
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

    if loader in _URL_LOADER_TYPES:
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

    # s3's loader accepts a dict or JSON string; pass it through unchanged.
    return remote_data
