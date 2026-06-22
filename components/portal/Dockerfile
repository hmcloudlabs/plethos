
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

# Install only the portal's deps + shared, baked into the venv (--no-editable),
# without dev tools. kopf and the controller's deps are excluded.
RUN uv sync --frozen --no-dev --no-editable --package portal

COPY components/portal/src components/portal/src

FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY --from=build /app/.venv .venv
COPY components/portal/src src
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
