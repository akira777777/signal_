FROM python:3.13.5-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install .
RUN mkdir -p /data /config /app/src/signal_group_sender/static /app/src/signal_group_sender/templates \
    && chown -R 65532:65532 /data /config /app

USER 65532:65532
ENTRYPOINT ["signal-groups"]
