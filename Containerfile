# Multi-stage build: uv resolves and installs into /app/.venv in the builder, the runtime stage
# only gets that venv. Builds with podman and docker:
#   podman build -f Containerfile -t odin .
#
# The package version normally comes from the git tag, but .git is not in the build context. CI
# passes it in instead:
#   podman build -f Containerfile --build-arg VERSION=1.2.3 --build-arg REVISION=<sha> -t odin .
# Without the build args (local builds) the version is the placeholder 0.0.0+unknown.

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
# Declared here, not at the top, so a new version does not invalidate the dependency layer.
ARG VERSION=0.0.0+unknown
RUN --mount=type=cache,target=/root/.cache/uv \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_ODIN="$VERSION" uv sync --locked --no-editable


FROM python:3.14-slim
RUN groupadd --system --gid 1000 odin \
    && useradd --system --uid 1000 --gid odin --home-dir /app --no-create-home odin \
    && mkdir -p /config /data \
    && chown odin:odin /data
COPY --from=builder --chown=odin:odin /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ODIN_CONFIG=/config/config.toml \
    ODIN_DB=/data/odin.db
VOLUME ["/config", "/data"]
USER odin
WORKDIR /app
# Last, so a new version only changes the metadata, not the cached layers above.
ARG VERSION=0.0.0+unknown
ARG REVISION=unknown
LABEL org.opencontainers.image.title="odin" \
      org.opencontainers.image.description="ODIN — Open Dinner Invitation Notifier" \
      org.opencontainers.image.source="https://github.com/Emrys-Merlin/odin" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION"
ENTRYPOINT ["odin"]
CMD ["run"]
