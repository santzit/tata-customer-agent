# ── Stage 1: Build Next.js static export ─────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

# Install dependencies first (cached layer)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy source and build
COPY frontend/ .
# API calls are relative (same origin) — no separate URL needed.
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build
# next build with output:"export" writes to ./out/


# ── Stage 2: Python FastAPI server ───────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy the Next.js static export built in stage 1 to /app/static/
# app/main.py mounts this directory as StaticFiles at "/"
COPY --from=frontend-builder /frontend/out /app/static

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
