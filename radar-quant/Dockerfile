FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
RUN mkdir -p /app/data
ENV RADAR_DATA_DIR=/app/data
EXPOSE 8430
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8430", "--workers", "1"]
