"""scheduled_messages

Revision ID: 0002_scheduled_messages
Revises: 0001_initial
Create Date: 2026-08-21 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0002_scheduled_messages'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create scheduled_messages table
    op.create_table(
        'scheduled_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('sender_id', sa.UUID(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('message_type', sa.String(length=20), nullable=False),
        sa.Column('scheduled_at_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timezone', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scheduled_messages_scheduled_at_utc'), 'scheduled_messages', ['scheduled_at_utc'], unique=False)

    # Alter messages table to add scheduled_message_id
    op.add_column('messages', sa.Column('scheduled_message_id', sa.UUID(), nullable=True))
    op.create_unique_constraint('uq_messages_scheduled_message_id', 'messages', ['scheduled_message_id'])
    op.create_foreign_key(
        'fk_messages_scheduled_messages',
        'messages', 'scheduled_messages',
        ['scheduled_message_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Drop foreign key and unique constraint
    op.drop_constraint('fk_messages_scheduled_messages', 'messages', type_='foreignkey')
    op.drop_constraint('uq_messages_scheduled_message_id', 'messages', type_='unique')
    op.drop_column('messages', 'scheduled_message_id')

    # Drop scheduled_messages table
    op.drop_index(op.f('ix_scheduled_messages_scheduled_at_utc'), table_name='scheduled_messages')
    op.drop_table('scheduled_messages')
