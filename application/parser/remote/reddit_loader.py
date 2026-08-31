import json
from typing import Any, Iterable, List

from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document

REQUIRED_FIELDS = ["client_id", "client_secret", "user_agent", "search_queries"]


class RedditPostsLoaderRemote(BaseRemote):
    """Load Reddit posts through praw.

    Create an app at https://www.reddit.com/prefs/apps/ to obtain the
    ``client_id`` and ``client_secret``.
    """

    def load_data(self, inputs) -> List[Document]:
        """Load posts for every configured subreddit or user.

        Args:
            inputs: JSON string holding the praw credentials plus
                ``search_queries``, and optionally ``mode``
                (``subreddit``/``username``), ``categories`` and
                ``number_posts``.

        Returns:
            One document per post, carrying the post body as text.
        """
        try:
            data = json.loads(inputs)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON input: {e}")

        missing_fields = [field for field in REQUIRED_FIELDS if field not in data]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        mode = data.get("mode", "subreddit")
        if mode not in ("subreddit", "username"):
            raise ValueError(
                "mode not correct, please enter 'username' or 'subreddit' as mode"
            )
        categories = data.get("categories", ["new", "hot"])
        search_queries = data.get("search_queries")
        number_posts = data.get("number_posts", 10)

        import praw

        reddit = praw.Reddit(
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            user_agent=data.get("user_agent"),
        )

        documents: List[Document] = []
        for search_query in search_queries:
            for category in categories:
                if mode == "subreddit":
                    listing = reddit.subreddit(search_query)
                else:
                    listing = reddit.redditor(search_query).submissions
                documents.extend(
                    self._posts_to_documents(
                        getattr(listing, category)(limit=number_posts), category
                    )
                )
        return documents

    @staticmethod
    def _posts_to_documents(posts: Iterable[Any], category: str) -> List[Document]:
        """Convert praw submissions into documents."""
        documents = []
        for post in posts:
            documents.append(
                Document(
                    text=post.selftext,
                    doc_id=post.id,
                    extra_info={
                        "post_subreddit": post.subreddit_name_prefixed,
                        "post_category": category,
                        "title": post.title,
                        "post_score": post.score,
                        "post_id": post.id,
                        "source": post.url,
                        "post_author": str(post.author),
                    },
                )
            )
        return documents
