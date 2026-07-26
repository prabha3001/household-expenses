FROM python:3.11-slim

# poppler-utils -> pdftotext (needed for Halifax statement parsing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium for Playwright PDF export
RUN python -m playwright install --with-deps chromium

COPY . .

RUN mkdir -p /app/data
ENV PORT=10000
EXPOSE 10000

# 2 workers is plenty for a small family app; each worker launches its own
# short-lived Chromium instance only when a PDF export is requested.
# --timeout is generous (10 minutes) to comfortably cover a big batch
# upload (many PDFs at once) on a slow free-tier instance, where each
# statement's parsing plus its database writes can take a while to add up.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 600 app:app"]
