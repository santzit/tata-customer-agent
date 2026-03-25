# Standalone frontend Dockerfile — produces a static export in /out.
# In production, the main Dockerfile builds this and copies /out into
# the FastAPI container so everything runs on port 8000.
# This file is kept for local frontend development only.
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# Serve the static export with a minimal HTTP server for local testing
FROM node:20-alpine AS runner
RUN npm install -g serve
WORKDIR /app
COPY --from=builder /app/out ./out
EXPOSE 3000
CMD ["serve", "-s", "out", "-l", "3000"]
