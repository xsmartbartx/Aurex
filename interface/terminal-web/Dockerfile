# AUREX web terminal: Next.js standalone server.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
# Rewrites are fixed at build time: where the web server forwards /api when no proxy sits in front of it.
ARG AUREX_API_INTERNAL_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 AUREX_API_INTERNAL_URL=$AUREX_API_INTERNAL_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 aurex
COPY --from=build --chown=aurex /app/.next/standalone ./
COPY --from=build --chown=aurex /app/.next/static ./.next/static
COPY --from=build --chown=aurex /app/public ./public
USER aurex
EXPOSE 3000
CMD ["node", "server.js"]
