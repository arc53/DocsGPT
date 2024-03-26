from application.parser.remote.base import BaseRemote
from langchain_community.document_loaders import RedditPostsLoader


class RedditPostsLoaderRemote(BaseRemote):
    def load_data(self, inputs):
        data = eval(inputs)
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")
        user_agent = data.get("user_agent")
        categories = data.get("categories", ["new", "hot"])
        mode = data.get("mode", "subreddit")
        search_queries = data.get("search_queries")
        self.loader = RedditPostsLoader(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            categories=categories,
            mode=mode,
            search_queries=search_queries,
            number_posts=10,
        )
        documents = self.loader.load()
        print(f"Loaded {len(documents)} documents from Reddit")
        return documents
