FROM python:3.11-slim
WORKDIR /app
COPY shared /app/shared
COPY services/report-agent /app/services/report-agent
RUN pip install --no-cache-dir -e /app/shared -r /app/services/report-agent/requirements.txt
WORKDIR /app/services/report-agent
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
