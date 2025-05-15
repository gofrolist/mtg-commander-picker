# 1. Build the React frontend
FROM node:24-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Install Python deps & gather backend + built frontend
FROM python:3.13-alpine AS backend-builder
WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy backend project files first
COPY backend/pyproject.toml backend/poetry.lock* /app/backend/

# Now change directory to the backend project folder to run poetry install
WORKDIR /app/backend/
RUN poetry config virtualenvs.in-project true \
    && poetry install --no-interaction

# Copy the rest of the backend code
COPY backend/ ./

# Copy the React build into the backend’s build folder
# The destination path is relative to the builder's WORKDIR (/app/backend)
COPY --from=frontend-builder /app/frontend/dist /app/backend/src/mtg_commander_picker/build/

# 3. Final runtime image
FROM python:3.13-alpine
WORKDIR /app

# Copy everything from builder
# This will copy the /app directory from the builder,
# which should now contain a 'backend' subdirectory at /app/backend
COPY --from=backend-builder /app /app

# Add /app to PYTHONPATH so Python can find the 'backend' package
ENV PYTHONPATH="/app/backend/src"
# Update PATH to include the poetry venv bin directory, which is inside backend/.venv
ENV PATH="/app/backend/.venv/bin:$PATH"

# Expose the port (must match your Flask/Gunicorn bind)
ENV PORT=8080
EXPOSE 8080

# Start the app - point Gunicorn to the backend.app module
# Assuming 'app' is the Flask instance name in backend/app.py
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "mtg_commander_picker.main:application"]
