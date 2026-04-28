FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app
COPY shared /app/shared
COPY --chown=appuser:appuser config /app/config
COPY services/supervisor-agent /app/services/supervisor-agent
RUN pip install --no-cache-dir --upgrade pip     && pip install --no-cache-dir -e /app/shared -r /app/services/supervisor-agent/requirements.txt

WORKDIR /app/services/supervisor-agent
USER appuser
EXPOSE 8003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
