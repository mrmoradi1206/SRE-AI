FROM python:3.11-slim
WORKDIR /app
COPY shared /app/shared
COPY services/supervisor-agent /app/services/supervisor-agent
RUN pip install --no-cache-dir -e /app/shared -r /app/services/supervisor-agent/requirements.txt
WORKDIR /app/services/supervisor-agent
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
