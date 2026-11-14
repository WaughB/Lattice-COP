# SPDX-License-Identifier: Apache-2.0
# Lattice-COP ingest image. Shared by the ais-ingest and adsb-ingest services.
#
# This image contains the proprietary Lattice SDK (installed from PyPI at build
# time). Build it locally only. Never push it to any registry.

FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=uv /uv /bin/uv
WORKDIR /build

# Dependencies first, so source edits do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE NOTICE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime

# Take Debian security fixes newer than the pinned base image, and drop pip:
# nothing installs packages at run time, and its bundled libraries carry CVEs.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --no-cache-dir pip \
    && groupadd --system --gid 10001 cop \
    && useradd --system --uid 10001 --gid cop --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin cop

# The virtualenv is copied whole: third-party license and notice files stay intact.
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 10001:10001

# Each Compose service overrides this with its own command.
CMD ["ais-ingest"]
