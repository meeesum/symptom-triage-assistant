import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# So `import app...` resolves the same way it does when running the app
# itself — migrations live in backend/migrations/, one level below
# backend/, where app/ lives.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DATABASE_URL  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.models import (  # noqa: E402,F401
    admin_action_log,
    alert,
    audit,
    chat_exchange,
    clinical_note,
    consent,
    data_request,
    kb_review,
    notification_preference,
    organization,
    patient_panel,
    referral,
    report_subscription,
    retention_purge_run,
    symptom_photo,
    user,
)

# refresh_token / revoked_token models are intentionally NOT imported here
# any more — that tracking moved to Redis (see app/services/refresh_tokens.py
# and app/services/token_revocation.py). Their tables were dropped by
# migrations/versions/*_move_token_tracking_to_redis.py.

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# DATABASE_URL (same env var the app itself reads — see app/core/config.py)
# is the single source of truth for which DB migrations run against.
# alembic.ini deliberately has no sqlalchemy.url of its own, so there's no
# second place this can drift out of sync with the app.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Base.metadata (with every model module imported above so they're
# registered on it) is what `alembic revision --autogenerate` diffs
# against — this is what makes autogenerate actually see our tables.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
