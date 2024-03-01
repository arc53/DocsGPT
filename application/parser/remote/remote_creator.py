from application.parser.remote.sitemap_loader import SitemapLoader
from application.parser.remote.crawler_loader import CrawlerLoader
from application.parser.remote.web_loader import WebLoader


class RemoteCreator:
    loaders = {
        'url': WebLoader,
        'sitemap': SitemapLoader,
        'crawler': CrawlerLoader
    }

    @classmethod
    def create_loader(cls, type, *args, **kwargs):
        loader_class = cls.loaders.get(type.lower())
        if not loader_class:
            raise ValueError(f"No LLM class found for type {type}")
        return loader_class(*args, **kwargs)