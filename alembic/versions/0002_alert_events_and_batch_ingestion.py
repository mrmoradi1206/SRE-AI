"""add alert_events and history ingestion support

Revision ID: 0002_alert_events_and_batch_ingestion
Revises: 0001_production_event_sourcing
Create Date: 2026-04-26 00:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_alert_events_and_batch_ingestion'
down_revision = '0001_production_event_sourcing'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('alert_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('event_type', sa.Text(), nullable=False, server_default='ingested'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alert_id', 'version', name='uq_alert_events_version'),
    )
    op.create_index('idx_alert_events_alert_id_created_at', 'alert_events', ['alert_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_alert_events_alert_id_created_at', table_name='alert_events')
    op.drop_table('alert_events')
