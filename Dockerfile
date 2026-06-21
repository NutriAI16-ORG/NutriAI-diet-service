FROM python:3.11-slim

# Create a non-root user and group
RUN groupadd -g 1000 appgroup && useradd -u 1000 -g appgroup -s /bin/sh appuser

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files and transfer ownership to non-root user
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
