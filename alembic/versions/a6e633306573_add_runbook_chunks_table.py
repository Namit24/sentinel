"""add runbook chunks table

Revision ID: a6e633306573
Revises: 73d05cc3db23
Create Date: 2026-04-02 01:31:00.617770

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = 'a6e633306573'
down_revision = '73d05cc3db23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('runbook_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.String(length=255), nullable=False),
    sa.Column('source_file', sa.String(length=255), nullable=False),
    sa.Column('section_title', sa.String(length=255), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('token_estimate', sa.Float(), nullable=False),
    sa.Column('embedding', Vector(dim=384), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_runbook_chunks_chunk_id'), 'runbook_chunks', ['chunk_id'], unique=True)
    op.create_index(op.f('ix_runbook_chunks_source_file'), 'runbook_chunks', ['source_file'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_runbook_chunks_source_file'), table_name='runbook_chunks')
    op.drop_index(op.f('ix_runbook_chunks_chunk_id'), table_name='runbook_chunks')
    op.drop_table('runbook_chunks')
