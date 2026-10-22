# Multi-platform index digest for the Official Python 3.11.17 slim-bookworm image.
# Refresh only through a reviewed base-image update and the container vulnerability scan.
FROM python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89

# The commit timestamp is supplied by CI and normalized by the OCI exporter.
ARG SOURCE_DATE_EPOCH=946684800
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Use a fixed Debian archive snapshot so apt does not resolve newer package versions on each build.
# Remove apt caches and logs from the image layer; they contain build-environment-specific metadata.
# Move the snapshot timestamp only in a reviewed update followed by the full container vulnerability scan.
RUN rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources \
    && printf '%s\n' \
        'Types: deb' \
        'URIs: https://snapshot.debian.org/archive/debian/20261017T000000Z' \
        'Suites: bookworm bookworm-updates' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        'Check-Valid-Until: no' \
        '' \
        'Types: deb' \
        'URIs: https://snapshot.debian.org/archive/debian-security/20261017T000000Z' \
        'Suites: bookworm-security' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        'Check-Valid-Until: no' \
        > /etc/apt/sources.list.d/debian-snapshot.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg espeak-ng ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/ldconfig/aux-cache /var/log/apt \
    && rm -f /var/log/dpkg.log /var/log/alternatives.log \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY app ./app

# uv 0.13.1 recognizes require-build-hashes and enforces build-constraint hashes.
# Avoid retaining ephemeral wheel/build caches in the runtime layer. uv's optional
# uv_cache.json records wall-clock install time, so remove it and its RECORD entry.
RUN python -m pip install --no-cache-dir "uv==0.13.1" \
    && uv sync --frozen --no-editable --no-cache \
    && python -c 'from pathlib import Path; sites=Path("/app/.venv/lib/python3.11/site-packages"); infos=list(sites.glob("vyralx-*.dist-info")); assert len(infos)==1, infos; info=infos[0]; cache=info/"uv_cache.json"; record=info/"RECORD"; prefix=(info.name+"/uv_cache.json,").encode(); rows=record.read_bytes().splitlines(keepends=True); matches=[row for row in rows if row.startswith(prefix)]; assert cache.is_file() and len(matches)==1, (cache, matches); record.write_bytes(b"".join(row for row in rows if not row.startswith(prefix))); cache.unlink()' \
    && python -m pip uninstall -y setuptools wheel uv \
    && rm -rf /root/.cache/uv /root/.cache/pip

ENV PATH="/app/.venv/bin:$PATH"
RUN mkdir -p /app/data /app/media /app/renders /app/secrets && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3); raise SystemExit(0 if r.status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
