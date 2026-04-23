FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências (camada cacheada separada do código)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código Django
COPY src/ /app/

# Copiar entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Criar pastas padrão (volumes sobrescrevem em runtime)
RUN mkdir -p /app/data /app/uploads /app/staticfiles

EXPOSE 8270

ENTRYPOINT ["/entrypoint.sh"]
