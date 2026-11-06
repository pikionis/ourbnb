# syntax=docker/dockerfile:1
#
# KosPM backend -- DEVELOPMENT image, used by the repo-root docker-compose.yml.
# It includes the dev dependency group (pytest, ruff, mypy, ...) and runs
# Django's runserver with hot reload over a bind mount of ./backend.
# The production image (gunicorn, non-root user, no dev deps) is Dockerfile.prod.
#
# After changing dependencies (pyproject.toml / uv.lock): docker compose build

FROM python:3.12-slim

# uv, pinned to the same version as local development and CI.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

# UV_PROJECT_ENVIRONMENT: the venv lives outside /app, so the ./backend bind
#   mount in docker-compose.yml does not hide it.
# UV_PYTHON / UV_PYTHON_DOWNLOADS: always use this image's interpreter (this
#   also overrides .python-version) and never download a managed Python.
# UV_LINK_MODE=copy: the uv cache is a separate mount, so hardlinks fail.
# UV_COMPILE_BYTECODE: compile site-packages once, at build time.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# 1) Third-party dependencies only. This layer is rebuilt only when
#    pyproject.toml or uv.lock change, not on every source edit.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# 2) Project source (manage.py, config/, src/kospm/, tests/), then install the
#    kospm package itself. uv installs it in editable mode (pointing at
#    /app/src), so the bind-mounted source is what actually runs.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

EXPOSE 8000

# manage.py defaults DJANGO_SETTINGS_MODULE to config.settings.dev.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
