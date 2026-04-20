"""add embedding column to incidents

Revision ID: 73d05cc3db23
Revises: 4d275d489fec
Create Date: 2026-04-02 01:17:41.430761

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = '73d05cc3db23'
down_revision = '4d275d489fec'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column('incidents', sa.Column('embedding', Vector(dim=384), nullable=True))


def downgrade() -> None:
    op.drop_column('incidents', 'embedding')
