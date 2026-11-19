# Production Dockerfile for FB Monitor (adhering to viseshrp/fbn architecture)
# Using official Playwright image with pre-installed Chromium and system dependencies
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Ho_Chi_Minh \
    DATA_DIR=/app/data \
    PORT=8000

# Set timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install Python requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

# Copy application source code
COPY . /app/

# Ensure persistent data directory exists
RUN mkdir -p /app/data

# Expose web application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/state || exit 1

# Start FastAPI application
CMD ["python", "main.py"]
