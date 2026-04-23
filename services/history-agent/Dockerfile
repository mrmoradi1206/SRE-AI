FROM python:3.11-slim
WORKDIR /app
COPY shared /app/shared
COPY services/history-agent /app/services/history-agent
RUN pip install --no-cache-dir -e /app/shared -r /app/services/history-agent/requirements.txt
WORKDIR /app/services/history-agent
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
