"""production event sourcing baseline

Revision ID: 0001_production_event_sourcing
Revises: 
Create Date: 2026-04-26 00:00:00
"""

from alembic import op

revision = '0001_production_event_sourcing'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(open('infra/postgres/init.sql', 'r', encoding='utf-8').read())


def downgrade() -> None:
    raise NotImplementedError('Downgrade not supported for baseline production schema')
