FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
RUN useradd --create-home cognition && mkdir -p /app/data && chown cognition:cognition /app/data
USER cognition
ENV DATABASE_PATH=/app/data/cognition.db
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Production bundles only compiled web assets; backend remains independently buildable.
FROM backend AS production
COPY --from=frontend /build/dist ./static
