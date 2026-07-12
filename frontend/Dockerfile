FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1

# Next.js inlines NEXT_PUBLIC_* references into the CLIENT (browser) bundle at
# `next build` time -- verified empirically against this exact build (grepping
# the compiled .next/static output). Setting NEXT_PUBLIC_SENTRY_DSN later as a
# `fly secrets set` runtime value has NO effect on browser-side Sentry; it
# only affects server-side code, which reads process.env live. So this must be
# a build ARG threaded through to a build-time ENV, not left to runtime. Empty
# default preserves the no-op-when-unset behavior (Sentry.init(...).enabled is
# `!!NEXT_PUBLIC_SENTRY_DSN` in instrumentation-client.ts / sentry.server.config.ts).
ARG NEXT_PUBLIC_SENTRY_DSN=""
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ARG NEXT_PUBLIC_SENTRY_RELEASE="dev"
ENV NEXT_PUBLIC_SENTRY_RELEASE=$NEXT_PUBLIC_SENTRY_RELEASE
RUN npm run build
RUN npm prune --omit=dev

FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder --chown=node:node /app/package.json ./package.json
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/next.config.ts ./next.config.ts

RUN mkdir -p /app/.next/cache && chown -R node:node /app

USER node

EXPOSE 3000

CMD ["npm", "run", "start"]
