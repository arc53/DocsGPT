from application.parser.remote.base import BaseRemote
from langchain_community.document_loaders import RedditPostsLoader


class RedditPostsLoaderRemote(BaseRemote):
    def load_data(self, inputs):
        client_id = inputs.get("client_id")
        client_secret = inputs.get("client_secret")
        user_agent = inputs.get("user_agent")
        categories = inputs.get("categories", ["new", "hot"])
        mode = inputs.get("mode", "subreddit")
        search_queries = inputs.get("search_queries")
        self.loader = RedditPostsLoader(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            categories=categories,
            mode=mode,
            search_queries=search_queries,
        )
        documents = []
        try:
            documents.extend(self.loader.load())
        except Exception as e:
            print(f"Error processing Data: {e}")
        print(f"Loaded {len(documents)} documents from Reddit")
        return documents[:5]
