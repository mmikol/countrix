# countrix: one image for every role - the door (the MCP server and its tools),
# the board with the inference engine, the refresher.
# compose.yaml runs one container per role from it; docker-entrypoint.sh picks
# the role.
FROM python:3.12-slim

# Nothing here runs as root. Files the containers write (caches, the playbook,
# the docs) stay owned by the bind mounts' owner: uid 1000 by default,
# COUNTRIX_UID/GID on a Linux host whose checkout belongs to someone else
# (compose.yaml).
RUN useradd --create-home --uid 1000 app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
# the runtime block only. Without pgserver: the embedded cluster is a host
# build target, and inside the image every container reaches a real postgres
# service over DATABASE_URL. Nor the development block: nothing in the image
# lints, type-checks or runs the tests (the host and CI do).
RUN grep -vE '^(pgserver|pytest|ruff|mypy)' requirements.txt | pip install --no-cache-dir -r /dev/stdin

COPY . .
RUN mkdir -p .cache-blizzard .cache-wiki \
    && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8017 8020

ENTRYPOINT ["./docker-entrypoint.sh"]
