FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements/flow_builder.txt /tmp/requirements-flow-builder.txt
RUN pip install --no-cache-dir -r /tmp/requirements-flow-builder.txt

COPY services/__init__.py ./services/__init__.py
COPY services/flow_builder ./services/flow_builder
COPY flow ./flow
COPY shared ./shared

CMD ["python", "-m", "services.flow_builder.worker"]
