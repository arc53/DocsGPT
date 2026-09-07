# DocsGPT frontend image: a static production build served by nginx.
#
# Vite inlines VITE_* settings at build time, so the old image ran the Vite
# dev server just to read VITE_API_HOST from the container environment. This
# image builds once and injects the container's VITE_* variables at start-up
# instead (docker/40-runtime-env.sh writes them to /config.js, which the app
# reads before its own bundle; see src/env.ts). Same env vars, same port.
#
# Targets:
#   (default)  nginx serving the built bundle -- what Docker Hub publishes
#   dev        the Vite dev server with hot reload, for docker-compose.yaml's
#              bind-mounted frontend (build: target: dev)

FROM node:22-alpine AS deps

WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund


FROM deps AS dev

COPY . .
# vite.config.ts polls the filesystem when DOCKER is set: native fs events do
# not cross a Windows host into a Linux container.
ENV DOCKER=1
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]


FROM deps AS build

COPY . .
# The image used to run the dev server, so .env.development was its set of
# defaults (notification banner, Google client id, local API host). Keep them
# as the production build's baseline; the container's VITE_* values override
# any of them at start-up.
RUN cp .env.development .env.production.local && \
    npm run build && \
    sed -i 's|<head>|<head><script src="/config.js"></script>|' dist/index.html


FROM nginx:1.27-alpine

LABEL org.opencontainers.image.source="https://github.com/arc53/DocsGPT" \
      org.opencontainers.image.title="DocsGPT frontend" \
      org.opencontainers.image.licenses="MIT"

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/40-runtime-env.sh /docker-entrypoint.d/40-runtime-env.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-env.sh
COPY --from=build /app/dist /usr/share/nginx/html

# Same port the dev server used, so compose files and docs keep working.
EXPOSE 5173
