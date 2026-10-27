FROM node:22-slim

# Versao fixa do cliente oficial headless do Obsidian Sync (CLI: ob)
RUN npm install -g obsidian-headless@0.0.14 && npm cache clean --force

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV HOME=/data/ob-home \
    TZ=America/Manaus

WORKDIR /data
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
