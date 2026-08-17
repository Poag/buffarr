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
# writable without any extra permission fixing. No named user/group is
# created -- useradd/groupadd fail outright if the base image already has
# any entry at that uid, gid, or name (Debian's base-passwd predefines a
# "users" group at gid 100, and apt itself creates system accounts like
# _apt in the same dynamic uid range), and the app never needs a
# resolvable username, so plain numeric ownership + USER sidesteps the
# whole class of conflict.
RUN mkdir -p /config && chown -R 99:100 /app /config
USER 99:100

EXPOSE 5099

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:5099/health || exit 1

CMD ["python", "src/main.py"]
