from alembic import op
import sqlalchemy as sa

revision = '0006_create_feedback_table'
down_revision = '0005_add_share_permissions'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Create the response_feedback table."""
    op.create_table(
        'response_feedback',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=False),
        sa.Column('response_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('feedback_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    
    op.create_index('ix_response_feedback_conversation_id', 'response_feedback', ['conversation_id'])
    op.create_index('ix_response_feedback_user_id', 'response_feedback', ['user_id'])
    op.create_index('ix_response_feedback_created_at', 'response_feedback', ['created_at'])

def downgrade() -> None:
    """Drop the response_feedback table."""
    op.drop_index('ix_response_feedback_created_at', table_name='response_feedback')
    op.drop_index('ix_response_feedback_user_id', table_name='response_feedback')
    op.drop_index('ix_response_feedback_conversation_id', table_name='response_feedback')
    op.drop_table('response_feedback')