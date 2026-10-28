FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

RUN uv pip install --system uv==0.13.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

ARG PYTHON_VERSION=3.14
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON=${PYTHON_VERSION}

RUN uv python install "${PYTHON_VERSION}"

WORKDIR /workspace

COPY . /workspace

RUN rm -rf .git \
    && git init \
    && git config user.email "ci@example.com" \
    && git config user.name "CI" \
    && git add -A \
    && git commit -m "snapshot"

RUN if [ "${PYTHON_VERSION}" = "3.15t" ]; then \
        curl --fail --silent --show-error https://sh.rustup.rs -o /tmp/rustup-init.sh \
        && sh /tmp/rustup-init.sh -y --profile minimal --no-modify-path \
            --default-toolchain 1.99.1 \
        && export PATH="/root/.cargo/bin:${PATH}"; \
    fi \
    && uv sync --frozen --group dev \
    && rm -rf /root/.cargo /root/.rustup /tmp/rustup-init.sh

RUN groupadd --system appuser \
    && useradd --system --gid appuser --create-home --home-dir /home/appuser appuser \
    && chown -R appuser:appuser /workspace

USER appuser

ENTRYPOINT []
