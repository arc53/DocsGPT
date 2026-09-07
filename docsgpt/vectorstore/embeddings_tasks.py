"""The Celery task behind :mod:`docsgpt.vectorstore.embeddings_delegated`.

Kept out of ``docsgpt.api.user.tasks`` deliberately: that module imports
``docsgpt.worker`` and the whole parsing stack with it, which is the
opposite of what delegation is for.
"""

from __future__ import annotations

from typing import List, Optional

from docsgpt.celery_init import celery
from docsgpt.vectorstore.embeddings_delegated import EMBED_TASK


@celery.task(name=EMBED_TASK, acks_late=False, ignore_result=False)
def embed_texts(texts: List[str], embeddings_name: Optional[str] = None) -> List[List[float]]:
    """Embed ``texts`` with the worker's local model.

    Args:
        texts: Strings to embed.
        embeddings_name: Model to use; the configured one when omitted.

    Returns:
        One vector per input, in input order.
    """
    from docsgpt.vectorstore.base import get_embeddings

    return get_embeddings(embeddings_name).embed_documents(list(texts))
