from application.parser.remote.sitemap_loader import SitemapLoader
from application.parser.remote.crawler_loader import CrawlerLoader
from application.parser.remote.web_loader import WebLoader
from application.parser.remote.reddit_loader import RedditPostsLoaderRemote
from application.parser.remote.github_loader import GitHubLoader


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
    }

    @classmethod
    def create_loader(cls, type, *args, **kwargs):
        loader_class = cls.loaders.get(type.lower())
        if not loader_class:
            raise ValueError(f"No loader class found for type {type}")
        return loader_class(*args, **kwargs)
