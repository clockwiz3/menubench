# Public demo image: the built Vue app served by FastAPI, "Try it" only by default.
# docker build -t menubench . && docker run -p 7860:7860 -e OPENROUTER_API_KEY=... menubench

FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src/ src/
COPY configs/ configs/
RUN uv sync --locked --no-dev
COPY --from=web /app/web/dist web/dist
RUN useradd --create-home app && mkdir -p data .cache && chown -R app data .cache
USER app

# The annotation tool writes to disk and spends money on pre-labelling: it stays off in public.
ENV MENUBENCH_SECTIONS=try \
    MENUBENCH_TRY_BUDGET_USD=1.0 \
    MENUBENCH_TRY_UPLOADS_PER_IP=10 \
    MENUBENCH_TRUST_PROXY=1 \
    PORT=7860
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
CMD ["sh", "-c", "uv run --no-sync menubench serve --host 0.0.0.0 --port ${PORT}"]
