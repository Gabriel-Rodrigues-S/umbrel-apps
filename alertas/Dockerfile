FROM python:3.12-slim
# tzdata: datas dos alertas no fuso do TZ (America/Manaus no compose)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alertas/ ./alertas/
ENV DADOS_DIR=/app/data
EXPOSE 8445
CMD ["uvicorn", "alertas.main:app", "--host", "0.0.0.0", "--port", "8445", "--workers", "1"]
