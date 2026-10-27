FROM python:3.12-slim
# git: usado pelo serviço de histórico (mesma imagem); tzdata: fuso do resumo diário
RUN apt-get update \
    && apt-get install -y --no-install-recommends git tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vault_gateway/ ./vault_gateway/
EXPOSE 8440
CMD ["uvicorn", "vault_gateway.servidor:app", "--host", "0.0.0.0", "--port", "8440", "--workers", "1"]
