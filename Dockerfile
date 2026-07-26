# syntax=docker/dockerfile:1

# ---------- Stage 1: build the React frontend ----------
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/yarn.lock ./
RUN yarn install --frozen-lockfile --no-audit
COPY frontend/ ./
ENV NODE_ENV=production
# Frontend and backend are served from the same origin in production (see server.py's
# SPA fallback route), so the API base is always relative — no per-environment rebuild needed.
ENV REACT_APP_BACKEND_URL=""
RUN yarn build

# ---------- Stage 2: backend runtime, also serves the built frontend ----------
FROM python:3.11-slim AS backend
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /app/frontend/build ./static

ENV FRONTEND_BUILD_DIR=/app/static \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
