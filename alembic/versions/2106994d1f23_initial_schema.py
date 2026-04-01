"""initial schema

Revision ID: 2106994d1f23
Revises: 
Create Date: 2026-04-02 01:06:32.266290

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2106994d1f23'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('alerts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('alert_id', sa.String(length=255), nullable=False),
    sa.Column('service_name', sa.String(length=255), nullable=False),
    sa.Column('severity', sa.String(length=32), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alerts_alert_id'), 'alerts', ['alert_id'], unique=True)
    op.create_index(op.f('ix_alerts_service_name'), 'alerts', ['service_name'], unique=False)
    op.create_index(op.f('ix_alerts_severity'), 'alerts', ['severity'], unique=False)
    op.create_table('incidents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('affected_services', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('raw_alert_ids', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('group_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence_score', sa.Float(), nullable=False),
    sa.Column('fallback_used', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incidents_status'), 'incidents', ['status'], unique=False)
    op.create_table('log_entries',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('service_name', sa.String(length=255), nullable=False),
    sa.Column('log_level', sa.String(length=32), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('trace_id', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_log_entries_log_level'), 'log_entries', ['log_level'], unique=False)
    op.create_index(op.f('ix_log_entries_service_name'), 'log_entries', ['service_name'], unique=False)
    op.create_index(op.f('ix_log_entries_trace_id'), 'log_entries', ['trace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_log_entries_trace_id'), table_name='log_entries')
    op.drop_index(op.f('ix_log_entries_service_name'), table_name='log_entries')
    op.drop_index(op.f('ix_log_entries_log_level'), table_name='log_entries')
    op.drop_table('log_entries')
    op.drop_index(op.f('ix_incidents_status'), table_name='incidents')
    op.drop_table('incidents')
    op.drop_index(op.f('ix_alerts_severity'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_service_name'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_alert_id'), table_name='alerts')
    op.drop_table('alerts')
