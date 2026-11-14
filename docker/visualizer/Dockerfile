# SPDX-License-Identifier: Apache-2.0
# Anduril's Entity Visualizer sample app, fetched from Anduril's own repository
# at a pinned commit and run unmodified. None of its code is in this repository.
#
# The app is covered by the Anduril Lattice SDK License Agreement (its
# LICENSE.md, kept intact in the image). Build this image locally only. Never
# push it to any registry.
#
# Credentials are passed at run time by Compose, not baked into the image.

FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS build

# Pinned upstream commit (2026-11-13). To update: change the SHA, rebuild, re-test.
ADD https://github.com/anduril/sample-app-entity-visualizer.git#439255e9be30f7b855f166cfce3709140d2b18d3 /app

WORKDIR /app
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS runtime

# Take Debian security fixes newer than the pinned base image. Drop the package
# managers: nothing is installed at run time, and their bundled libraries carry CVEs.
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
        /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
        /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
        /opt/yarn-* /usr/local/bin/yarn /usr/local/bin/yarnpkg

# Vite writes its dependency cache under node_modules/.vite, so the app
# directory belongs to the unprivileged user that runs it.
COPY --from=build --chown=1000:1000 /app /app

WORKDIR /app
ENV NODE_ENV=development
# UID and GID 1000 are the image's built-in "node" user.
USER 1000:1000
EXPOSE 5173

# Same as upstream's `npm run dev` ("vite"), listening on the container
# interface. Compose publishes the port on 127.0.0.1 only.
CMD ["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
