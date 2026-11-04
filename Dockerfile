# Multi-stage build for agybridge
FROM python:3.13-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

# Install tzdata, jemalloc and set timezone
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata libjemalloc2 && \
    ln -sf /usr/share/zoneinfo/UTC /etc/localtime && \
    echo "UTC" > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Use jemalloc instead of glibc malloc to reduce memory fragmentation
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2
ENV MALLOC_CONF="background_thread:true,dirty_decay_ms:5000,muzzy_decay_ms:5000"

WORKDIR /app

# Copy dependencies first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 7861

# Start via web.py
CMD ["python", "web.py"]
