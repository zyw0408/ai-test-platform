FROM node:20-bookworm-slim AS deps

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared-schema/package.json packages/shared-schema/package.json

RUN npm ci

FROM node:20-bookworm-slim AS builder

WORKDIR /app

ARG PLATFORM_API_URL=http://api:8000
ARG NEXT_PUBLIC_PLATFORM_API_URL=http://localhost:8000

ENV NEXT_TELEMETRY_DISABLED=1
ENV PLATFORM_API_URL=$PLATFORM_API_URL
ENV NEXT_PUBLIC_PLATFORM_API_URL=$NEXT_PUBLIC_PLATFORM_API_URL

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/package.json ./apps/web/package.json
COPY --from=deps /app/packages/shared-schema/package.json ./packages/shared-schema/package.json
COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/web ./apps/web
COPY packages/shared-schema ./packages/shared-schema

RUN npm --workspace packages/shared-schema run typecheck
RUN npm --workspace apps/web run build

FROM node:20-bookworm-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV PLATFORM_API_URL=http://api:8000
ENV NEXT_PUBLIC_PLATFORM_API_URL=http://localhost:8000

COPY --from=builder /app/apps/web/.next/standalone ./
COPY --from=builder /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /app/apps/web/public ./apps/web/public

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
