FROM python:3.12-slim

# System packages: nginx, supervisord, espeak-ng (required by piper-phonemize)
RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx \
        supervisor \
        espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
RUN pip install --no-cache-dir \
    "piper-tts>=1.2.0" \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0"

# Download pt-BR voice model at build time (~63 MB baked into image)
RUN python3 -c "\
import urllib.request, pathlib; \
d = pathlib.Path('/app/models'); d.mkdir(exist_ok=True); \
base = 'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/'; \
[( \
    print('Downloading', f, '...'), \
    urllib.request.urlretrieve(base + f, d / f), \
    print('Done:', f) \
) for f in ['pt_BR-faber-medium.onnx', 'pt_BR-faber-medium.onnx.json']]"

# Application files
COPY backend.py         /app/backend.py
COPY supervisord.conf   /etc/supervisor/conf.d/tts.conf
COPY nginx.conf         /etc/nginx/nginx.conf
COPY index.html         /usr/share/nginx/html/index.html

EXPOSE 80
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/tts.conf"]
