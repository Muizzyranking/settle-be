"""create_payouts_table

Revision ID: 5c8f3a1b2e9d
Revises: d72e90d15a27
Create Date: 2026-07-07 23:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '5c8f3a1b2e9d'
down_revision: Union[str, Sequence[str], None] = 'd72e90d15a27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payouts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('fee', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('destination_account_number', sa.String(20), nullable=False),
        sa.Column('destination_account_name', sa.String(255), nullable=False),
        sa.Column('destination_bank_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('transaction_ref', sa.String(255), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('payouts')
