# Servidor dedicado oficial do Terraria (vanilla) + painel de controle.
#
# Para atualizar o Terraria: trocar TERRARIA_VERSAO abaixo pela versão nova
# (a mesma do jogo no Steam), subir a versão em garod004-apps-terraria/umbrel-app.yml,
# apontar o image: do compose para a tag nova e dar push. Os mundos ficam em
# ${APP_DATA_DIR}/data e não são tocados pela atualização.
FROM debian:bookworm-slim
LABEL org.opencontainers.image.source=https://github.com/Gabriel-Rodrigues-S/umbrel-apps

ARG TERRARIA_VERSAO=1.4.5.8

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl unzip python3 tzdata; \
    num="$(echo "$TERRARIA_VERSAO" | tr -d .)"; \
    curl -fsSL -o /tmp/servidor.zip "https://terraria.org/api/download/pc-dedicated-server/terraria-server-${num}.zip"; \
    unzip -q /tmp/servidor.zip "${num}/Linux/*" -d /tmp/servidor; \
    mv "/tmp/servidor/${num}/Linux" /opt/terraria; \
    chmod +x /opt/terraria/TerrariaServer /opt/terraria/TerrariaServer.bin.x86_64; \
    rm -rf /tmp/servidor /tmp/servidor.zip; \
    apt-get purge -y curl unzip; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

COPY painel/ /opt/painel/

ENV TERRARIA_VERSAO=${TERRARIA_VERSAO} \
    TERRARIA_DIR=/opt/terraria \
    DATA_DIR=/data \
    PAINEL_PORTA=7878 \
    PORTA_JOGO=7777 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Manaus

EXPOSE 7777 7878
VOLUME /data
# O supervisor começa como root só para acertar o dono de /data e já troca
# para o usuário 1000 (o mesmo do Umbrel) antes de ligar o servidor.
CMD ["python3", "/opt/painel/main.py"]
