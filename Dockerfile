# AUREX backend: one image runs the API, the worker and the migration job (ADR-0002).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY core core
COPY modules modules
COPY security security
COPY pipelines pipelines
COPY interface/__init__.py interface/__init__.py
COPY interface/api interface/api
COPY migrations migrations
COPY alembic.ini ./

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 aurex
WORKDIR /app
COPY --from=build --chown=aurex:aurex /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 AUREX_DEPLOYMENT_MODE=self_hosted
USER aurex
EXPOSE 8000
CMD ["uvicorn", "interface.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
