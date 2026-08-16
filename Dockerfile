FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUFFARR_CONFIG_DIR=/config

# System deps (CA certs, curl for the healthcheck, tzdata for TZ handling)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config.example.toml .

# uid 99 / gid 100 match Unraid's own nobody:users convention, so a mounted
# /config appdata share (typically already owned 99:100 on Unraid) is
# writable without any extra permission fixing.
RUN (getent group 100 || groupadd -g 100 users) && \
    useradd --create-home --uid 99 --gid 100 --shell /usr/sbin/nologin buffarr && \
    mkdir -p /config && \
    chown -R buffarr:buffarr /app /config
USER buffarr

EXPOSE 5099

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:5099/health || exit 1

CMD ["python", "src/main.py"]
