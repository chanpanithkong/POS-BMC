# PIMS frontend (Next.js) production image.
#
# NEXT_PUBLIC_* values are baked into the browser code at build time, so pass the API address
# the USERS' BROWSERS will call (not Docker's internal "api" host name):
#
#   docker build -t pims-frontend --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 .
#   docker run -p 3000:3000 pims-frontend
#
# Change the address = build the image again.

# 1. Dependencies (cached until package.json or the lockfile changes)
FROM node:24-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# 2. Build
FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ARG NEXT_PUBLIC_API_MODE=live
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_API_MODE=$NEXT_PUBLIC_API_MODE \
    NEXT_TELEMETRY_DISABLED=1 \
    BUILD_STANDALONE=1
RUN npm run build

# 3. Run: only the standalone server, static assets and public files; no source, no dev tools
FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 pims && adduser -S -u 10001 -G pims pims
COPY --from=builder --chown=pims:pims /app/.next/standalone ./
COPY --from=builder --chown=pims:pims /app/.next/static ./.next/static
COPY --from=builder --chown=pims:pims /app/public ./public
USER pims
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/login || exit 1
CMD ["node", "server.js"]
