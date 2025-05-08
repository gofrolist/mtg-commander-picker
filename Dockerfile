# 1. Build the React frontend
FROM node:24-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Install Python deps & gather backend + built frontend
FROM python:3.13-alpine AS backend-builder
WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy and install backend deps
COPY backend/pyproject.toml backend/poetry.lock* ./
RUN poetry config virtualenvs.in-project true \
    && poetry install --no-interaction

# Copy backend code
COPY backend/ ./

# Copy the React build into the backend’s static folder
COPY --from=frontend-builder /app/frontend/dist ./build

# 3. Final runtime image
FROM python:3.13-alpine
WORKDIR /app

# Copy everything from builder
COPY --from=backend-builder /app /app

ENV PATH="/app/.venv/bin:$PATH"
# Expose the port (must match your Flask/Gunicorn bind)
ENV PORT=8080
EXPOSE 8080

# Start the app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
