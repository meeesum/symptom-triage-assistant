"""add organizations table and users org_id

Revision ID: 678c75d13f55
Revises: 59f62aaff9c4
Create Date: 2026-08-19 17:19:47.159467

Hand-edited beyond the autogenerate output (see app/services/organizations.py's
module docstring for why this is the right place to seed the default org,
not a lazy-create in application code): adds a "Default Organization" row
(slug="default", matching DEFAULT_ORG_SLUG) so every pre-existing
single-tenant workflow — every test, every already-registered user —
keeps working unchanged, then backfills every existing users.org_id to
point at it before making the column NOT NULL. The three-step
add-nullable / backfill / tighten-to-not-null sequence (rather than
adding the column NOT NULL directly) is required because existing rows
have no value to satisfy a NOT NULL constraint at add-column time; the
final tighten is done via batch mode for SQLite compatibility (SQLite
can't ALTER COLUMN directly — batch mode recreates the table under the
hood), which also works unchanged against Postgres.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '678c75d13f55'
down_revision: Union[str, None] = '59f62aaff9c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_ORG_SLUG = "default"
_DEFAULT_ORG_NAME = "Default Organization"


def upgrade() -> None:
    org_table = op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)

    # Seed the default org and capture its real generated id — assuming
    # id=1 would work for a fresh table on both SQLite and Postgres, but
    # reading it back from the INSERT is correct regardless of any prior
    # state, so that's what this does instead of hardcoding.
    connection = op.get_bind()
    result = connection.execute(
        org_table.insert().values(name=_DEFAULT_ORG_NAME, slug=_DEFAULT_ORG_SLUG)
    )
    default_org_id = result.inserted_primary_key[0]

    op.add_column('users', sa.Column('org_id', sa.Integer(), nullable=True))
    users_table = sa.table('users', sa.column('org_id', sa.Integer()))
    connection.execute(users_table.update().values(org_id=default_org_id))

    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('org_id', nullable=False)
        batch_op.create_index(op.f('ix_users_org_id'), ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_org_id'), table_name='users')
    op.drop_column('users', 'org_id')
    op.drop_index(op.f('ix_organizations_slug'), table_name='organizations')
    op.drop_table('organizations')
