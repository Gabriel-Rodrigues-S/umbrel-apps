#!/usr/bin/env python3
"""Decide quais apps precisam de build e publica a matriz para o GitHub Actions.

Regras:
- push na main: só entram os apps cujos arquivos de código mudaram entre o commit
  anterior ao push (BEFORE_SHA) e o atual (GITHUB_SHA).
- workflow_dispatch: INPUT_APPS = "todos" ou lista separada por vírgula.
- Se não der para comparar os commits (primeiro push, force-push), publica todos.
- Mudanças só em manifests (garod004-apps-*/), README ou no próprio workflow
  não geram build.
"""
import json
import os
import re
import subprocess
import sys

# nome do app -> imagem no GHCR, contexto do build, pasta do manifest Umbrel
# (de onde sai a versão) e caminhos que, ao mudar, exigem reconstruir a imagem.
# Terminar em "/" significa "qualquer arquivo dentro da pasta".
APPS = {
    "video-downloader": {
        "image": "yt-downloader",
        "context": ".",
        "manifest": "garod004-apps-video-downloader",
        "paths": ["Dockerfile", "requirements.txt", "app/"],
    },
    "realassessoria": {
        "image": "real-assessoria",
        "context": "./realassessoria",
        "manifest": "garod004-apps-realassessoria",
        "paths": ["realassessoria/"],
    },
    "file-converter": {
        "image": "file-converter",
        "context": "./file-converter",
        "manifest": "garod004-apps-file-converter",
        "paths": ["file-converter/"],
    },
    "tts-reader": {
        "image": "tts-reader",
        "context": "./tts-reader",
        "manifest": "garod004-apps-tts-reader",
        "paths": ["tts-reader/"],
    },
    "sistema-edah": {
        "image": "sistema-edah",
        "context": "./sistema-edah",
        "manifest": "garod004-apps-sistema-edah",
        "paths": ["sistema-edah/"],
    },
    "crypto-paper-bot": {
        "image": "crypto-paper-bot",
        "context": "./crypto-paper-bot",
        "manifest": "garod004-apps-crypto-paper-bot",
        "paths": ["crypto-paper-bot/"],
    },
    "painel-mercado": {
        "image": "painel-mercado",
        "context": "./painel-mercado",
        "manifest": "garod004-apps-painel-mercado",
        "paths": ["painel-mercado/"],
    },
}

VERSAO_RE = re.compile(r"^version:\s*['\"]?(\d+\.\d+\.\d+)['\"]?\s*$", re.MULTILINE)


def log(msg):
    print(msg, file=sys.stderr)


def versao_do_manifest(app):
    caminho = os.path.join(APPS[app]["manifest"], "umbrel-app.yml")
    with open(caminho, encoding="utf-8") as f:
        m = VERSAO_RE.search(f.read())
    if not m:
        sys.exit(f"Não achei uma versão X.Y.Z em {caminho}")
    return m.group(1)


def arquivos_alterados(antes, depois):
    """Lista de arquivos alterados, ou None se não der para comparar."""
    if not antes or set(antes) == {"0"}:
        return None
    r = subprocess.run(
        ["git", "diff", "--name-only", antes, depois],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log(f"git diff falhou ({r.stderr.strip()}); vou publicar todos os apps.")
        return None
    return [l for l in r.stdout.splitlines() if l]


def mudou(app, arquivos):
    for p in APPS[app]["paths"]:
        for f in arquivos:
            if (p.endswith("/") and f.startswith(p)) or f == p:
                return True
    return False


def escolher():
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        pedido = (os.environ.get("INPUT_APPS") or "todos").strip()
        if pedido.lower() == "todos":
            return list(APPS), "execução manual: todos os apps"
        nomes = [n.strip() for n in pedido.split(",") if n.strip()]
        invalidos = [n for n in nomes if n not in APPS]
        if invalidos:
            sys.exit(f"App(s) desconhecido(s): {', '.join(invalidos)}. Válidos: {', '.join(APPS)}")
        return nomes, "execução manual: " + ", ".join(nomes)

    arquivos = arquivos_alterados(os.environ.get("BEFORE_SHA", ""), os.environ.get("GITHUB_SHA", "HEAD"))
    if arquivos is None:
        return list(APPS), "sem base de comparação: todos os apps"
    escolhidos = [a for a in APPS if mudou(a, arquivos)]
    return escolhidos, f"{len(arquivos)} arquivo(s) alterado(s) no push"


def main():
    escolhidos, motivo = escolher()
    matriz = [
        {
            "app": a,
            "image": APPS[a]["image"],
            "context": APPS[a]["context"],
            "version": versao_do_manifest(a),
        }
        for a in escolhidos
    ]
    log(f"Motivo: {motivo}")
    for item in matriz:
        log(f"  -> {item['app']}  (imagem {item['image']}, versão {item['version']})")
    if not matriz:
        log("Nenhum app com código alterado; nada a publicar.")

    saidas = {"matriz": json.dumps(matriz), "tem": "true" if matriz else "false"}
    destino = os.environ.get("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            for k, v in saidas.items():
                f.write(f"{k}={v}\n")
    else:
        print(json.dumps(saidas, ensure_ascii=False))

    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            f.write(f"### Apps a publicar\n\n{motivo}\n\n")
            if matriz:
                f.write("| App | Imagem | Versão |\n|---|---|---|\n")
                for i in matriz:
                    f.write(f"| {i['app']} | `{i['image']}` | {i['version']} |\n")
            else:
                f.write("Nenhum app com código alterado.\n")


if __name__ == "__main__":
    main()
