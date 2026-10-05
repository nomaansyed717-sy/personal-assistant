FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY app ./app

RUN useradd --create-home appuser && chmod -R a+rX /ms-playwright
USER appuser

# Web + scheduler in one process by default (RUN_WORKER_IN_WEB=true). For a separate worker,
# set RUN_WORKER_IN_WEB=false here and run a second service with: python -m app.worker.run
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
