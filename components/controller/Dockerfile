FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Manifests + lock first for layer caching. All workspace members' pyproject
# files are needed so uv can validate the workspace against the lock.
COPY pyproject.toml uv.lock ./
COPY components/portal/pyproject.toml components/portal/pyproject.toml
COPY components/controller/pyproject.toml components/controller/pyproject.toml
COPY components/shared/pyproject.toml components/shared/pyproject.toml
# shared SOURCE is needed so uv can build it into the venv.
COPY components/shared/src components/shared/src

# Install only the controller's deps + shared, baked into the venv
# (--no-editable), without dev tools. fastapi and the portal's deps are excluded.
RUN uv sync --frozen --no-dev --no-editable --package controller

COPY components/controller/src components/controller/src

# ---- runtime ----
FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY --from=build /app/.venv .venv
COPY components/controller/src src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"
USER app

CMD ["kopf", "run", "src/main.py", "--all-namespaces"]
