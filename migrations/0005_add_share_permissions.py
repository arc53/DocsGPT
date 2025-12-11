from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005_add_share_permissions'
down_revision = '0004_initial_shares'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Add permission columns to allow granular share control."""
    # This adds columns to an existing table
    # If the table doesn't exist yet, this migration creates it
    
    op.create_table(
        'conversation_shares',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=False),
        sa.Column('share_token', sa.String(), nullable=False),
        sa.Column('allow_prompting', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('allow_editing', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('share_token'),
    )
    op.create_index('ix_conversation_shares_conversation_id', 'conversation_shares', ['conversation_id'])
    op.create_index('ix_conversation_shares_token', 'conversation_shares', ['share_token'])

def downgrade() -> None:
    """Downgrade: drop the shares table."""
    op.drop_index('ix_conversation_shares_token', table_name='conversation_shares')
    op.drop_index('ix_conversation_shares_conversation_id', table_name='conversation_shares')
    op.drop_table('conversation_shares')