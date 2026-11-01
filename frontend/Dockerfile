# syntax=docker/dockerfile:1

# CloneVoice web app image (RAILWAY_READINESS_REPORT.md F-02).
#
# Build from the REPO ROOT, like the API and worker images:
#   docker build -f frontend/Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com/api/v1 \
#     --build-arg NEXT_PUBLIC_APP_ORIGIN=https://app.example.com -t clonevoice-web .
# On Railway, every service variable is passed as a build argument for the ARGs declared
# below, so set NEXT_PUBLIC_* on the web service before the first deploy.
# Same major as CI (frontend/.nvmrc); Next 16 needs Node >= 20.9.
FROM node:26-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39 AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# NEXT_PUBLIC_* is inlined into the client bundle at build time (and read by the CSP
# middleware at run time), so changing either value needs a rebuild. lib/env.ts fails the
# build loudly if the API URL is missing or invalid.
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_APP_ORIGIN
ARG NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_APP_ORIGIN=$NEXT_PUBLIC_APP_ORIGIN \
    NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM node:26-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Only what `next start` needs. Root-owned and read-only to the app user.
COPY --from=build /app/package.json /app/package-lock.json /app/next.config.mjs ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next

# The image's built-in unprivileged user (uid 1000).
USER node

# `next start` listens on $PORT (Railway injects it; 3000 otherwise) on all interfaces.
EXPOSE 3000
CMD ["npm", "run", "start"]
