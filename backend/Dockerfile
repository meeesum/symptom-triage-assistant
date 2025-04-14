# Multi-stage build: install deps in a builder layer, copy only the
# installed packages + app code into the final image — keeps the shipped
# image free of build toolchains (gcc etc, needed to build some wheels)
# that the running app never needs.

FROM python:3.13-slim AS builder

WORKDIR /build

# build-essential: some deps (e.g. scikit-learn's own transitive deps)
# may need to compile from source depending on platform/wheel availability.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# Migrations are NOT run here (no ENTRYPOINT calling scripts/migrate.py) —
# see app/core/migrate.py's docstring for why: run migrations once, as an
# explicit deploy step, before starting any app instance, not as a race
# between N container replicas all starting at once. The app's own
# lifespan hook still runs them for local/dev convenience (e.g. `docker
# run` without a separate migrate step), just not relied on here.
EXPOSE 8000

# Structured JSON logs by default in a container context — see
# app/core/logging_config.py. Override at `docker run` time if needed.
ENV ENVIRONMENT=production

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
