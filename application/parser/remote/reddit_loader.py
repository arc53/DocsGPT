from application.parser.remote.base import BaseRemote
from langchain_community.document_loaders import RedditPostsLoader
import json


class RedditPostsLoaderRemote(BaseRemote):
    def load_data(self, inputs):
        try:
            data = json.loads(inputs)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON input: {e}")

        required_fields = ["client_id", "client_secret", "user_agent", "search_queries"]
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")
        user_agent = data.get("user_agent")
        categories = data.get("categories", ["new", "hot"])
        mode = data.get("mode", "subreddit")
        search_queries = data.get("search_queries")
        number_posts = data.get("number_posts", 10)
        self.loader = RedditPostsLoader(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            categories=categories,
            mode=mode,
            search_queries=search_queries,
            number_posts=number_posts,
        )
        documents = self.loader.load()
        print(f"Loaded {len(documents)} documents from Reddit")
        return documents
