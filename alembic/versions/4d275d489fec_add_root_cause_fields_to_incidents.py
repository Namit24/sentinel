"""add root cause fields to incidents

Revision ID: 4d275d489fec
Revises: 2106994d1f23
Create Date: 2026-04-02 01:17:00.681236

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '4d275d489fec'
down_revision = '2106994d1f23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('incidents', sa.Column('root_cause_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('incidents', sa.Column('top_cause_service', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_incidents_top_cause_service'), 'incidents', ['top_cause_service'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_incidents_top_cause_service'), table_name='incidents')
    op.drop_column('incidents', 'top_cause_service')
    op.drop_column('incidents', 'root_cause_data')
