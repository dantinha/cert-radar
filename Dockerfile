FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    CERT_RADAR_HOST=0.0.0.0

WORKDIR /app

# Copy package metadata and source first
COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
COPY config ./config

# Install package and runtime dependencies
RUN pip install --no-cache-dir -e .

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", 10000)}/api/health')" || exit 1

CMD ["python", "-m", "cert_radar", "serve", "--no-browser"]
