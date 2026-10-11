FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md NOTICE SECURITY.md ./
COPY ino_a9_bridge/src ./ino_a9_bridge/src

RUN python -m pip install --no-cache-dir .

USER 65532:65532

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"]

ENTRYPOINT ["wificam-bridge"]
CMD ["--config", "/run/wificam/camera.json"]
