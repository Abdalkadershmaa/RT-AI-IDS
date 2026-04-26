FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements/inference.txt /tmp/requirements-inference.txt
RUN pip install --no-cache-dir -r /tmp/requirements-inference.txt

COPY services/__init__.py ./services/__init__.py
COPY services/inference ./services/inference
COPY shared ./shared
COPY models ./models

CMD ["python", "-m", "services.inference.worker"]
