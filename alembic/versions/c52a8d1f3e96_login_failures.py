"""login failures

Revision ID: c52a8d1f3e96
Revises: b41f6c2d8e57
Create Date: 2026-09-26 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c52a8d1f3e96'
down_revision: Union[str, Sequence[str], None] = 'b41f6c2d8e57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'login_failures',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('ip', sa.String(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_login_failures_username'), 'login_failures', ['username'], unique=False)
    op.create_index(op.f('ix_login_failures_ip'), 'login_failures', ['ip'], unique=False)
    op.create_index(op.f('ix_login_failures_occurred_at'), 'login_failures', ['occurred_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_login_failures_occurred_at'), table_name='login_failures')
    op.drop_index(op.f('ix_login_failures_ip'), table_name='login_failures')
    op.drop_index(op.f('ix_login_failures_username'), table_name='login_failures')
    op.drop_table('login_failures')
