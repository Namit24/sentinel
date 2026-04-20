"""add policy and pipeline metrics to incidents

Revision ID: 96f2f9f54e14
Revises: a73faeec6f20
Create Date: 2026-04-11 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '96f2f9f54e14'
down_revision = 'a73faeec6f20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('incidents', sa.Column('pipeline_metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('incidents', sa.Column('policy_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('incidents', 'policy_data')
    op.drop_column('incidents', 'pipeline_metrics')
