# syntax=docker/dockerfile:1
#
# Wonderland Court in a container, with `court` as the entrypoint. Ollama stays on the host:
# the container reaches it at OLLAMA_HOST, which defaults to the host's port 11434. On Linux,
# add `--add-host=host.docker.internal:host-gateway`, or set OLLAMA_HOST (or court.yaml) to
# another server.
#
#   docker build -t wonderland-court .
#   docker run --rm -v "$PWD:/work" wonderland-court trial --quick --mock
#   docker run --rm -v "$PWD:/work" wonderland-court ci --fail-above 0.10
#   docker run --rm -p 8000:8000 -v "$PWD:/work" wonderland-court serve --host 0.0.0.0
#
# Runs are written to court.yaml's db_path under /work. On Linux, pass
# `--user "$(id -u):$(id -g)"` so the files belong to you.

# Both stages use the same Python image, so the environment's interpreter path stays valid.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, from the lockfile alone, so a source change doesn't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM ${PYTHON_IMAGE}
RUN groupadd --system --gid 999 court \
    && useradd --system --uid 999 --gid 999 --create-home court
COPY --from=build --chown=court:court /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=http://host.docker.internal:11434
USER court
WORKDIR /work
EXPOSE 8000
ENTRYPOINT ["court"]
CMD ["--help"]
