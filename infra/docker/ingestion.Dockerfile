FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpcap0.8 tcpdump \
 && rm -rf /var/lib/apt/lists/*

COPY requirements/ingestion.txt /tmp/requirements-ingestion.txt
RUN pip install --no-cache-dir -r /tmp/requirements-ingestion.txt

COPY services/__init__.py ./services/__init__.py
COPY services/ingestion ./services/ingestion
COPY shared ./shared

CMD ["python", "-m", "services.ingestion.run_sniffer"]
