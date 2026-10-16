# backend/Dockerfile - Python FastAPI container

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (minimal for production)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Expose FastAPI port
EXPOSE 8000

# Environment variable for Python
ENV PYTHONUNBUFFERED=1

# Create non-root user for security
RUN useradd -m appuser
USER appuser

# Start application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]