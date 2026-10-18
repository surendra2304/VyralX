# Multi-platform index digest for the Official Python 3.11.17 slim-bookworm image.
# Refresh only through a reviewed base-image update and the container vulnerability scan.
FROM python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
RUN python -m pip install --no-cache-dir "uv==0.12.18" \
    && uv sync --frozen --no-editable \
    && python -m pip uninstall -y setuptools wheel uv
ENV PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /app/data /app/media /app/renders /app/secrets && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3); raise SystemExit(0 if r.status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
