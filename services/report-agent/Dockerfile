FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app
COPY shared /app/shared
COPY services/report-agent /app/services/report-agent
RUN pip install --no-cache-dir --upgrade pip     && pip install --no-cache-dir -e /app/shared -r /app/services/report-agent/requirements.txt

WORKDIR /app/services/report-agent
USER appuser
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
