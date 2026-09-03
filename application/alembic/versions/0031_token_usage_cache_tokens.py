"""0031 token_usage cache tokens — persist the prompt-cache breakdown.

Providers report how much of each prompt was served from the prompt cache
(``cached_tokens``) and, on newer OpenAI-family models, how much was written
to it (``cache_write_tokens``). The LLM clients already parsed both and the
usage layer discarded them, so ``token_usage`` could not show a cache hit
rate. These two nullable columns carry the breakdown; NULL means the
provider reported nothing (distinct from 0). ``prompt_tokens`` keeps its
meaning as the provider's total. Idempotent both ways.

Revision ID: 0031_token_usage_cache_tokens
Revises: 0030_superseded_messages
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0031_token_usage_cache_tokens"
down_revision: Union[str, None] = "0030_superseded_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS cached_tokens integer;")
    op.execute(
        "ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS cache_write_tokens integer;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS cache_write_tokens;")
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS cached_tokens;")
