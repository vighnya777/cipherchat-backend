"""add username_lower for case-insensitive uniqueness

Revision ID: 8f3a1c9d2b47
Revises: 4d833ab63dac
Create Date: 2026-08-12 00:00:00.000000

Adds users.username_lower — a lowercased mirror of `username` with a unique
constraint, so that case-variant duplicates ("Bob" vs "bob") can never both
be inserted, including under concurrent registration requests. Backfilled
from the existing `username` column for pre-existing rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8f3a1c9d2b47'
down_revision: Union[str, None] = '4d833ab63dac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('username_lower', sa.String(length=64), nullable=True))
    users = sa.table('users', sa.column('username', sa.String), sa.column('username_lower', sa.String))
    op.execute(users.update().values(username_lower=sa.func.lower(users.c.username)))
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('username_lower', existing_type=sa.String(length=64), nullable=False)
    op.create_index(op.f('ix_users_username_lower'), 'users', ['username_lower'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_username_lower'), table_name='users')
    op.drop_column('users', 'username_lower')
