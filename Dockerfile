# ORAKL Bot - Production Docker Image
# Optimized for cloud deployment (Railway, Render, DigitalOcean, etc.)

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV TZ=America/New_York

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import psutil; import sys; sys.exit(0 if any('main.py' in ' '.join(p.cmdline()) for p in psutil.process_iter(['cmdline'])) else 1)"

# Run the bot
CMD ["python", "-u", "main.py"]
