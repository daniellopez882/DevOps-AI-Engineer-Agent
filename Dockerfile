FROM python:3.12-slim AS build

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# Only the application modules. The previous image did `COPY . .`, which
# would have baked a local .env -- every provider key -- into the image.
COPY --chown=app:app *.py ./

RUN mkdir -p /app/data && chown app:app /app/data
VOLUME ["/app/data"]

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////app/data/devops_os.db \
    BIND_HOST=0.0.0.0 \
    PORT=8000

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["sh", "-c", "uvicorn main:app --host ${BIND_HOST} --port ${PORT}"]
