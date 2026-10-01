#!/usr/bin/env python3
"""Supervisor do servidor dedicado do Terraria + painel web para o Umbrel.

- Liga o TerrariaServer oficial como subprocesso e fala com ele pelo stdin
  (comandos do console) e pelo stdout (log, jogadores entrando/saindo).
- Faz backup automático do mundo a cada BACKUP_HORAS e sempre que o app é
  desligado (inclusive antes de cada atualização pelo Umbrel).
- Serve o painel em PAINEL_PORTA (atrás do app_proxy do Umbrel). O jogo em si
  usa a porta PORTA_JOGO, publicada direto no host.
Só biblioteca padrão do Python, sem dependências.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

DATA = os.environ.get("DATA_DIR", "/data")
MUNDOS = os.path.join(DATA, "Worlds")
BACKUPS = os.path.join(DATA, "backups")
ESTADO_ARQ = os.path.join(DATA, "painel.json")
HOME = os.path.join(DATA, "home")
TERRARIA_DIR = os.environ.get("TERRARIA_DIR", "/opt/terraria")
VERSAO = os.environ.get("TERRARIA_VERSAO", "?")
PAINEL_PORTA = int(os.environ.get("PAINEL_PORTA", "7878"))
PORTA_JOGO = int(os.environ.get("PORTA_JOGO", "7777"))
MAX_JOGADORES = int(os.environ.get("MAX_JOGADORES", "8"))
SENHA = os.environ.get("SENHA_MUNDO", "")
BACKUP_HORAS = float(os.environ.get("BACKUP_HORAS", "6"))
BACKUPS_MANTER = int(os.environ.get("BACKUPS_MANTER", "30"))
ENDERECO = os.environ.get("ENDERECO_CONEXAO", "")
UID = int(os.environ.get("PUID", "1000"))
GID = int(os.environ.get("PGID", "1000"))
MAX_UPLOAD = 200 * 1024 * 1024

NOME_OK = re.compile(r"^[\w .()\-]+\.wld$")
ENTROU = re.compile(r"^(?::\s*)?(.+) has joined\.$")
SAIU = re.compile(r"^(?::\s*)?(.+) has left\.$")
PROGRESSO = re.compile(r"^(.*?)\s*\d+%$")

trava = threading.RLock()


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ler_estado():
    try:
        with open(ESTADO_ARQ, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def gravar_estado(estado):
    tmp = ESTADO_ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ESTADO_ARQ)


def listar_mundos():
    try:
        return sorted(n for n in os.listdir(MUNDOS) if n.endswith(".wld"))
    except OSError:
        return []


def mundo_atual():
    mundos = listar_mundos()
    escolhido = ler_estado().get("mundo")
    if escolhido in mundos:
        return escolhido
    return mundos[0] if mundos else None


def listar_backups():
    try:
        nomes = [n for n in os.listdir(BACKUPS) if n.endswith(".wld")]
    except OSError:
        return []
    itens = []
    for n in sorted(nomes, reverse=True):
        st = os.stat(os.path.join(BACKUPS, n))
        itens.append({"nome": n, "tamanho": st.st_size,
                      "data": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")})
    return itens


class Servidor:
    def __init__(self):
        self.proc = None
        self.status = "parado"  # parado | iniciando | online | parando | sem_mundo | erro
        self.log = deque(maxlen=400)
        self.jogadores = []
        self.inicio = None
        self.mundo = None
        self.quer_rodando = True
        self.falhas = 0
        self.ultimo_backup = None

    # ---------- log ----------
    def anotar(self, linha):
        linha = linha.rstrip()
        if not linha.strip():
            return
        m = PROGRESSO.match(linha)
        if m and self.log:
            anterior = PROGRESSO.match(self.log[-1][1])
            if anterior and anterior.group(1) == m.group(1):
                self.log[-1] = (self.log[-1][0], linha)
                return
        self.log.append((agora(), linha))

    def ler_saida(self, proc):
        buf = b""
        while True:
            pedaco = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
            if not pedaco:
                break
            buf += pedaco
            partes = re.split(rb"[\r\n]", buf)
            buf = partes.pop()
            for p in partes:
                self.tratar_linha(p.decode("utf-8", "replace"))
        if buf:
            self.tratar_linha(buf.decode("utf-8", "replace"))

    def tratar_linha(self, linha):
        texto = linha.strip()
        with trava:
            self.anotar(linha)
            if "Server started" in texto:
                self.status = "online"
                self.falhas = 0
            m = ENTROU.match(texto)
            if m and m.group(1) not in self.jogadores:
                self.jogadores.append(m.group(1))
            m = SAIU.match(texto)
            if m and m.group(1) in self.jogadores:
                self.jogadores.remove(m.group(1))

    # ---------- ciclo de vida ----------
    def iniciar(self):
        with trava:
            if self.proc and self.proc.poll() is None:
                return
            self.quer_rodando = True
            self.mundo = mundo_atual()
            if not self.mundo:
                self.status = "sem_mundo"
                self.anotar("[painel] Nenhum mundo em Worlds/. Envie um arquivo .wld pelo painel.")
                return
            config = os.path.join(DATA, "serverconfig.txt")
            linhas = [
                f"world={os.path.join(MUNDOS, self.mundo)}",
                f"worldpath={MUNDOS}",
                f"port={PORTA_JOGO}",
                f"maxplayers={MAX_JOGADORES}",
                "secure=0",
            ]
            if SENHA:
                linhas.append(f"password={SENHA}")
            with open(config, "w", encoding="utf-8") as f:
                f.write("\n".join(linhas) + "\n")
            env = dict(os.environ, HOME=HOME, MONO_IOMAP="all")
            self.anotar(f"[painel] Iniciando Terraria {VERSAO} com o mundo {self.mundo}")
            self.proc = subprocess.Popen(
                ["./TerrariaServer.bin.x86_64", "-config", config],
                cwd=TERRARIA_DIR, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.status = "iniciando"
            self.jogadores = []
            self.inicio = time.time()
            threading.Thread(target=self.ler_saida, args=(self.proc,), daemon=True).start()

    def parar(self, motivo="parada pedida"):
        with trava:
            self.quer_rodando = False
            proc = self.proc
            if not proc or proc.poll() is not None:
                self.status = "parado"
                return
            online = self.status == "online"
            self.status = "parando"
            self.anotar(f"[painel] Desligando o servidor ({motivo}); o mundo é salvo antes de sair.")
        try:
            if online:
                self.comando("exit")
                proc.wait(timeout=90)
            else:
                proc.terminate()
                proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.anotar("[painel] O servidor não respondeu; encerrando à força.")
            proc.kill()
            proc.wait()
        with trava:
            self.status = "parado"
            self.jogadores = []

    def reiniciar(self):
        self.parar("reinício")
        self.iniciar()

    def comando(self, texto):
        with trava:
            proc = self.proc
            if not proc or proc.poll() is not None:
                return False
            try:
                proc.stdin.write((texto.strip() + "\n").encode("utf-8"))
                proc.stdin.flush()
            except OSError:
                return False
            self.anotar(f"> {texto.strip()}")
            return True

    def vigiar(self):
        """Religa o servidor se ele cair sozinho."""
        while True:
            time.sleep(5)
            with trava:
                caiu = self.proc and self.proc.poll() is not None and self.quer_rodando
                if caiu:
                    self.falhas += 1
                    self.status = "erro"
                    self.jogadores = []
                    self.anotar(f"[painel] O servidor parou (código {self.proc.returncode}).")
            if caiu:
                if self.falhas > 5:
                    self.anotar("[painel] Caiu 5 vezes seguidas; não vou religar sozinho. Use o botão Reiniciar.")
                    with trava:
                        self.quer_rodando = False
                    continue
                time.sleep(10 * self.falhas)
                self.iniciar()

    # ---------- backup ----------
    def salvar_e_esperar(self, timeout=90):
        """Manda 'save' e espera o arquivo do mundo parar de mudar."""
        caminho = os.path.join(MUNDOS, self.mundo or "")
        antes = os.path.getmtime(caminho) if os.path.exists(caminho) else 0
        if not (self.status == "online" and self.comando("save")):
            return
        limite = time.time() + timeout
        while time.time() < limite:
            time.sleep(1)
            if os.path.exists(caminho) and os.path.getmtime(caminho) > antes:
                break
        estavel = 0
        ultimo = None
        while time.time() < limite and estavel < 3:
            time.sleep(1)
            atual = os.path.getmtime(caminho), os.path.getsize(caminho)
            estavel = estavel + 1 if atual == ultimo else 0
            ultimo = atual

    def backup(self, motivo):
        mundo = self.mundo or mundo_atual()
        if not mundo:
            return None
        self.salvar_e_esperar()
        origem = os.path.join(MUNDOS, mundo)
        if not os.path.exists(origem):
            return None
        os.makedirs(BACKUPS, exist_ok=True)
        base = mundo[:-4]
        destino = os.path.join(BACKUPS, f"{base}_{datetime.now():%Y-%m-%d_%H%M%S}.wld")
        shutil.copy2(origem, destino)
        self.ultimo_backup = time.time()
        with trava:
            self.anotar(f"[painel] Backup criado ({motivo}): {os.path.basename(destino)}")
        self.limpar_backups()
        return os.path.basename(destino)

    def limpar_backups(self):
        itens = sorted(n for n in os.listdir(BACKUPS) if n.endswith(".wld"))
        for n in itens[:-BACKUPS_MANTER] if len(itens) > BACKUPS_MANTER else []:
            os.remove(os.path.join(BACKUPS, n))

    def backups_periodicos(self):
        while True:
            time.sleep(60)
            if BACKUP_HORAS <= 0 or self.status != "online":
                continue
            ref = self.ultimo_backup or self.inicio or time.time()
            if time.time() - ref >= BACKUP_HORAS * 3600:
                try:
                    self.backup("automático")
                except OSError as e:
                    self.anotar(f"[painel] Falha no backup automático: {e}")

    def restaurar(self, nome):
        origem = os.path.join(BACKUPS, nome)
        mundo = self.mundo or mundo_atual()
        if not os.path.exists(origem) or not mundo:
            raise ValueError("backup ou mundo não encontrado")
        if not nome.startswith(mundo[:-4] + "_"):
            raise ValueError(f"esse backup não é do mundo {mundo}")
        self.backup("antes de restaurar")
        self.parar("restauração de backup")
        shutil.copy2(origem, os.path.join(MUNDOS, mundo))
        self.anotar(f"[painel] Mundo {mundo} restaurado a partir de {nome}")
        self.iniciar()

    def resumo(self):
        with trava:
            return {
                "status": self.status,
                "versao": VERSAO,
                "mundo": self.mundo,
                "mundos": listar_mundos(),
                "jogadores": list(self.jogadores),
                "max_jogadores": MAX_JOGADORES,
                "endereco": ENDERECO,
                "porta": PORTA_JOGO,
                "senha": bool(SENHA),
                "online_desde": self.inicio if self.status == "online" else None,
                "backup_horas": BACKUP_HORAS,
                "backups_manter": BACKUPS_MANTER,
                "backups": listar_backups(),
                "log": [f"{t}  {l}" for t, l in list(self.log)[-200:]],
            }


srv = Servidor()
PAGINA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


class Painel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def responder(self, codigo, corpo, tipo="application/json; charset=utf-8", extras=None):
        if isinstance(corpo, (dict, list)):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        elif isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extras or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def erro(self, msg, codigo=400):
        self.responder(codigo, {"ok": False, "erro": msg})

    def json_corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def enviar_arquivo(self, caminho, nome):
        tamanho = os.path.getsize(caminho)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(tamanho))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(nome)}")
        self.end_headers()
        with open(caminho, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/":
            with open(PAGINA, "rb") as f:
                return self.responder(200, f.read(), "text/html; charset=utf-8")
        if url.path == "/api/estado":
            return self.responder(200, srv.resumo())
        if url.path == "/api/backup/baixar":
            nome = (q.get("nome") or [""])[0]
            caminho = os.path.join(BACKUPS, nome)
            if not NOME_OK.match(nome) or not os.path.exists(caminho):
                return self.erro("backup não encontrado", 404)
            return self.enviar_arquivo(caminho, nome)
        if url.path == "/api/mundo/baixar":
            nome = (q.get("nome") or [""])[0]
            caminho = os.path.join(MUNDOS, nome)
            if not NOME_OK.match(nome) or not os.path.exists(caminho):
                return self.erro("mundo não encontrado", 404)
            return self.enviar_arquivo(caminho, nome)
        self.erro("não encontrado", 404)

    def do_POST(self):
        url = urlparse(self.path)
        corpo = self.json_corpo()
        try:
            if url.path == "/api/salvar":
                if not srv.comando("save"):
                    return self.erro("o servidor não está rodando")
                return self.responder(200, {"ok": True})
            if url.path == "/api/backup":
                nome = srv.backup("manual")
                return self.responder(200, {"ok": bool(nome), "nome": nome})
            if url.path == "/api/reiniciar":
                threading.Thread(target=srv.reiniciar, daemon=True).start()
                return self.responder(200, {"ok": True})
            if url.path == "/api/parar":
                threading.Thread(target=srv.parar, daemon=True).start()
                return self.responder(200, {"ok": True})
            if url.path == "/api/iniciar":
                srv.falhas = 0
                srv.iniciar()
                return self.responder(200, {"ok": True})
            if url.path == "/api/comando":
                texto = str(corpo.get("comando", "")).strip()
                if not texto or texto.lower() in ("exit", "exit-nosave"):
                    return self.erro("use os botões para desligar o servidor")
                if not srv.comando(texto):
                    return self.erro("o servidor não está rodando")
                return self.responder(200, {"ok": True})
            if url.path == "/api/mundo/selecionar":
                nome = str(corpo.get("nome", ""))
                if nome not in listar_mundos():
                    return self.erro("mundo não encontrado")
                estado = ler_estado()
                estado["mundo"] = nome
                gravar_estado(estado)
                threading.Thread(target=srv.reiniciar, daemon=True).start()
                return self.responder(200, {"ok": True})
            if url.path == "/api/backup/restaurar":
                nome = str(corpo.get("nome", ""))
                if not NOME_OK.match(nome):
                    return self.erro("nome inválido")
                threading.Thread(target=self._restaurar, args=(nome,), daemon=True).start()
                return self.responder(200, {"ok": True})
        except (OSError, ValueError) as e:
            return self.erro(str(e), 500)
        self.erro("não encontrado", 404)

    def _restaurar(self, nome):
        try:
            srv.restaurar(nome)
        except (OSError, ValueError) as e:
            srv.anotar(f"[painel] Falha ao restaurar: {e}")

    def do_PUT(self):
        """Recebe um .wld no corpo cru da requisição: PUT /api/mundo/enviar?nome=X.wld"""
        url = urlparse(self.path)
        if url.path != "/api/mundo/enviar":
            return self.erro("não encontrado", 404)
        nome = os.path.basename(unquote((parse_qs(url.query).get("nome") or [""])[0]))
        n = int(self.headers.get("Content-Length") or 0)
        if not NOME_OK.match(nome):
            return self.erro("o arquivo precisa ser um .wld (letras, números, espaço, _ - . ( ))")
        if not 0 < n <= MAX_UPLOAD:
            return self.erro("arquivo vazio ou grande demais")
        os.makedirs(MUNDOS, exist_ok=True)
        destino = os.path.join(MUNDOS, nome)
        tmp = destino + ".enviando"
        with open(tmp, "wb") as f:
            restante = n
            while restante:
                bloco = self.rfile.read(min(1 << 20, restante))
                if not bloco:
                    break
                f.write(bloco)
                restante -= len(bloco)
        if restante:
            os.remove(tmp)
            return self.erro("envio incompleto")
        substituir = os.path.exists(destino)
        em_uso = substituir and nome == srv.mundo and srv.status in ("online", "iniciando")
        if em_uso:
            srv.backup("antes de substituir pelo envio")
            srv.parar("substituição do mundo")
        elif substituir:
            os.makedirs(BACKUPS, exist_ok=True)
            shutil.copy2(destino, os.path.join(BACKUPS, f"{nome[:-4]}_{datetime.now():%Y-%m-%d_%H%M%S}.wld"))
        os.replace(tmp, destino)
        srv.anotar(f"[painel] Mundo recebido: {nome} ({n // 1024} KB)")
        if em_uso or srv.status in ("sem_mundo", "parado", "erro"):
            srv.falhas = 0
            threading.Thread(target=srv.iniciar, daemon=True).start()
        self.responder(200, {"ok": True, "nome": nome})


def preparar_pastas_e_usuario():
    for d in (DATA, MUNDOS, BACKUPS, HOME):
        os.makedirs(d, exist_ok=True)
    if os.getuid() == 0:
        # Pastas criadas pelo Docker nascem como root; devolve tudo ao usuário
        # do Umbrel e larga o root antes de ligar o servidor.
        for raiz, dirs, arqs in os.walk(DATA):
            for n in [raiz] + [os.path.join(raiz, x) for x in dirs + arqs]:
                try:
                    os.chown(n, UID, GID)
                except OSError:
                    pass
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)


def main():
    preparar_pastas_e_usuario()
    http = ThreadingHTTPServer(("0.0.0.0", PAINEL_PORTA), Painel)
    http.daemon_threads = True

    def desligar(sig, _frame):
        # Chamado no 'docker stop' (desligar/atualizar o app no Umbrel).
        def tarefa():
            if srv.status == "online":
                try:
                    srv.backup("app desligando")
                except OSError as e:
                    srv.anotar(f"[painel] Falha no backup de desligamento: {e}")
            srv.parar("app desligando")
            http.shutdown()
        threading.Thread(target=tarefa, daemon=True).start()

    signal.signal(signal.SIGTERM, desligar)
    signal.signal(signal.SIGINT, desligar)
    srv.iniciar()
    threading.Thread(target=srv.vigiar, daemon=True).start()
    threading.Thread(target=srv.backups_periodicos, daemon=True).start()
    print(f"Painel em :{PAINEL_PORTA}, jogo em :{PORTA_JOGO}", flush=True)
    http.serve_forever()
    sys.exit(0)


if __name__ == "__main__":
    main()
