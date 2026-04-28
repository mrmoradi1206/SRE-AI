FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app
COPY shared /app/shared
COPY --chown=appuser:appuser config /app/config
COPY services/history-agent /app/services/history-agent
RUN pip install --no-cache-dir --upgrade pip     && pip install --no-cache-dir -e /app/shared -r /app/services/history-agent/requirements.txt

WORKDIR /app/services/history-agent
USER appuser
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
