# Build on the Mac for linux/amd64; the server only loads and runs the image.
FROM --platform=$BUILDPLATFORM node:24-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund --fetch-timeout=60000 --fetch-retries=1
COPY next.config.ts tsconfig.json ./
COPY src ./src
COPY skills ./skills
COPY 确定性计算层 ./确定性计算层
COPY rag/standard-status.json ./rag/standard-status.json
COPY engineering-adapters ./engineering-adapters
COPY source/adapter_runtime ./source/adapter_runtime
RUN npm run build

# Install target-specific optional binaries without emulating npm itself.
FROM --platform=$BUILDPLATFORM node:24-bookworm-slim AS runtime-deps
WORKDIR /app
ARG TARGETARCH
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    case "$TARGETARCH" in amd64) npm_cpu=x64 ;; arm64) npm_cpu=arm64 ;; *) exit 1 ;; esac \
    && npm ci --omit=dev --ignore-scripts --cpu="$npm_cpu" --os=linux --libc=glibc \
       --no-audit --no-fund --fetch-timeout=60000 --fetch-retries=1

FROM node:24-bookworm-slim AS node-runtime

FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/requirements.txt /tmp/requirements.txt
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && /app/.venv/bin/pip check
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=runtime-deps /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.ts ./next.config.ts
COPY --from=build /app/src ./src
COPY --from=build /app/skills ./skills
COPY --from=build /app/确定性计算层 ./确定性计算层
COPY --from=build /app/rag ./rag
COPY --from=build /app/engineering-adapters ./engineering-adapters
COPY --from=build /app/source/adapter_runtime ./source/adapter_runtime
COPY tools/access/manage.mjs ./tools/access/manage.mjs
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/var /app/.next/cache \
    && chown -R app:app /app/var /app/.next/cache
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \
    EXCAVAGUARD_PYTHON=/app/.venv/bin/python \
    EXCAVAGUARD_ACCESS_FILE=/app/var/access/directory.json \
    EXCAVAGUARD_PROJECT_STANDARDS_ROOT=/app/var/project-standards \
    EXCAVAGUARD_PROJECT_CONTEXT_ROOT=/app/var/project-context \
    EXCAVAGUARD_UPLOAD_ROOT=/app/var/uploads \
    EXCAVAGUARD_RUN_ROOT=/app/var/runs
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
