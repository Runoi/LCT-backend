"""session expiry

Revision ID: b41f6c2d8e57
Revises: a7c3e91d4b20
Create Date: 2026-09-26 15:00:00.000000

Existing sessions are backfilled with created_at + 480 minutes (the default
SESSION_TTL_MINUTES) so that no pre-existing token stays valid forever.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b41f6c2d8e57'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91d4b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sessions', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE sessions SET expires_at = created_at + interval '480 minutes' WHERE expires_at IS NULL")
    op.alter_column('sessions', 'expires_at', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sessions', 'expires_at')
