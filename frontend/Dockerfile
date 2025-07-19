# Multi-stage build using Next.js's `output: "standalone"` (next.config.js)
# — the final image ships only the production dependency subset Next.js
# actually traced as needed, not the full node_modules tree from the
# build stage.

FROM node:20-slim AS builder

WORKDIR /build

COPY package*.json ./
RUN npm ci

COPY . .
# NEXT_PUBLIC_* vars are baked in at build time (client-side env), not
# read at runtime — set the real API URL here for a production build.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build


FROM node:20-slim

WORKDIR /app

COPY --from=builder /build/.next/standalone ./
COPY --from=builder /build/.next/static ./.next/static
COPY --from=builder /build/public ./public

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
