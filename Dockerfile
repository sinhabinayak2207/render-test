FROM python:3.12-slim

# WeasyPrint native deps (Pango / Cairo / GDK-Pixbuf) + fonts so the PDF report
# renders properly. These are the libs that are missing on Windows — on Linux
# (Render) they install cleanly via apt, so WeasyPrint works out of the box.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi-dev shared-mime-info fonts-dejavu fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching). The pipeline/ingest worker
# needs the extra extraction libs in requirements-pipeline.txt.
COPY requirements.txt requirements-pipeline.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-pipeline.txt

COPY . .

# Render injects $PORT (defaults to 10000 here for local docker runs).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
