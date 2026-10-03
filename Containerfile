# Multi-stage build: uv resolves and installs into /app/.venv in the builder, the runtime stage
# only gets that venv. Builds with podman and docker:
#   podman build -f Containerfile -t odib .

FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_DEV=1
WORKDIR /app

# Dependencies first, so this layer is cached while only the source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable


FROM python:3.14-slim
RUN groupadd --system --gid 1000 odib \
    && useradd --system --uid 1000 --gid odib --home-dir /app --no-create-home odib \
    && mkdir -p /config /data \
    && chown odib:odib /data
COPY --from=builder --chown=odib:odib /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ODIB_CONFIG=/config/config.toml \
    ODIB_DB=/data/odib.db
VOLUME ["/config", "/data"]
USER odib
WORKDIR /app
ENTRYPOINT ["odib"]
CMD ["run"]
