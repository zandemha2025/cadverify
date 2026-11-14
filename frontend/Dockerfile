FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ARG NEXT_PUBLIC_VERIFY_UI=1
ARG NEXT_PUBLIC_DESIGN_INTELLIGENCE=1
ARG NEXT_PUBLIC_SHOW_DEV_TOOLS=0
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_VERIFY_UI=$NEXT_PUBLIC_VERIFY_UI \
    NEXT_PUBLIC_DESIGN_INTELLIGENCE=$NEXT_PUBLIC_DESIGN_INTELLIGENCE \
    NEXT_PUBLIC_SHOW_DEV_TOOLS=$NEXT_PUBLIC_SHOW_DEV_TOOLS
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
RUN npm prune --omit=dev

FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["npm", "run", "start"]
