FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TESSERA_HOST=0.0.0.0 \
    TESSERA_PORT=8765 \
    TESSERA_DB=/app/data/workbench.sqlite3 \
    TESSERA_LOG_LEVEL=normal

WORKDIR /app

COPY server.py core.py store.py samples.py proof.py ./
COPY ai ./ai
COPY webcraft ./webcraft
COPY research ./research
COPY static ./static

RUN useradd --create-home --uid 10001 tessera \
    && mkdir -p /app/data \
    && chown -R tessera:tessera /app

USER tessera

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"

CMD ["python", "-B", "server.py"]
