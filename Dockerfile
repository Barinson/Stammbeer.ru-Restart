# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Версионирование сборки: значения приходят из docker compose build args.
ARG APP_VERSION=0.1.0
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

LABEL org.opencontainers.image.title="stammbeer-app" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

WORKDIR /app

# Внешних зависимостей нет — приложение использует только стандартную библиотеку Python.
COPY . /app

# Непривилегированный пользователь; каталог var/ (SQLite + медиа) должен быть ему доступен на запись.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var \
    && chown -R appuser:appuser /app/var
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"]

CMD ["python", "-m", "app.main"]
