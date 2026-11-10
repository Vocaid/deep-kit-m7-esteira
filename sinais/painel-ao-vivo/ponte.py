"""Ponte serial -> navegador para o painel ao vivo do M7 (so biblioteca padrao + pyserial).

Le a serial do Mega (firmware diag_ao_vivo, ou o firmware do M7 da aula), grava cada linha com horario num
arquivo por sessao em sinais/sessoes/painel/ (pasta ignorada pelo git) e repassa ao navegador:
  /eventos    Server-Sent Events, cada evento = "<epoch_ms>|<linha>"
  /historico  JSON [[epoch_ms, linha], ...] das ultimas linhas em memoria (?desde=<epoch_ms>&max=N)
  /sessao     JSON com o arquivo da sessao, inicio e contagem de linhas
  /baixar     o arquivo da sessao (texto: ISO \t epoch_ms \t linha)
  /comando    POST 'T' (teste das saidas) ou 'P' (tom no buzzer): so o firmware diag_ao_vivo entende
Serve o index.html desta pasta. So 127.0.0.1; nada sai da maquina.

uso (na raiz do repositorio):
  sinais/.venv/bin/python -I sinais/painel-ao-vivo/ponte.py --serial /dev/cu.usbmodemXXXX
e abra http://localhost:8000/  -- Ctrl-C fecha a porta serial (so um programa por porta).
Atencao: no macOS, abrir a porta reseta o Mega 2560 (DTR da USB). Ligar a ponte = recalibrar (33 s).
"""
import argparse, collections, datetime, http.server, json, os, queue, threading, time, urllib.parse
import serial

PASTA = os.path.dirname(os.path.abspath(__file__))
PASTA_SESSOES = os.path.join(os.path.dirname(PASTA), "sessoes", "painel")
assinantes, trava = [], threading.Lock()
porta_serial = {"s": None}       # aberta por ler_serial; usada tambem por POST /comando
COMANDOS = {b"T", b"P"}          # T = teste das saidas; P = tom no buzzer (firmware diag_ao_vivo)
historico = collections.deque(maxlen=60000)   # ~50 min a 20 linhas/s, ou ~16 h a 1 linha/s
sessao = {"arquivo": None, "inicio": None, "linhas": 0, "f": None}


def agora_ms():
    return int(time.time() * 1000)


def registra(linha, prefixo=""):
    t = agora_ms()
    texto = prefixo + linha
    with trava:
        historico.append((t, texto))
        sessao["linhas"] += 1
        f = sessao["f"]
        if f:
            f.write(f"{datetime.datetime.fromtimestamp(t / 1000).isoformat(timespec='milliseconds')}\t{t}\t{texto}\n")
            f.flush()
        for q in list(assinantes):
            try:
                q.put_nowait(f"{t}|{texto}")
            except queue.Full:
                pass


def ler_serial(porta, parar):
    """Le a serial; se o USB cair (cabo puxado, upload de firmware), registra e tenta reabrir a cada 2 s."""
    caiu = False
    while not parar.is_set():
        try:
            s = serial.Serial(porta, 115200, timeout=0.2)
        except (serial.SerialException, OSError):
            if not caiu:
                registra(f"porta {porta} indisponivel; tentando de novo a cada 2 s", prefixo="> ponte: ")
                caiu = True
            parar.wait(2)
            continue
        if caiu:
            registra(f"porta {porta} reaberta (o Mega reseta ao abrir)", prefixo="> ponte: ")
            caiu = False
        porta_serial["s"] = s
        try:
            while not parar.is_set():
                linha = s.readline().decode("utf-8", "replace").strip()
                if linha:
                    registra(linha)
        except (serial.SerialException, OSError):
            registra(f"porta {porta} caiu (USB desconectado?)", prefixo="> ponte: ")
            caiu = True
        finally:
            porta_serial["s"] = None
            try:
                s.close()
            except Exception:
                pass
        parar.wait(2)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=PASTA, **k)

    def log_message(self, *a):
        pass

    def _json(self, obj):
        corpo = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        if self.path != "/comando":
            self.send_error(404)
            return
        corpo = self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 8)).strip()
        s = porta_serial["s"]
        if corpo not in COMANDOS or s is None:
            self.send_error(400, "comando invalido ou serial fechada")
            return
        s.write(corpo)
        registra(corpo.decode(), prefixo="> comando ")
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/historico":
            desde = int(q.get("desde", ["0"])[0])
            maximo = min(int(q.get("max", ["20000"])[0]), 60000)
            with trava:
                itens = [x for x in historico if x[0] >= desde]
            return self._json(itens[-maximo:])
        if url.path == "/sessao":
            with trava:
                return self._json({"arquivo": sessao["arquivo"], "inicio": sessao["inicio"],
                                   "linhas": sessao["linhas"], "em_memoria": len(historico)})
        if url.path == "/baixar":
            if not sessao["arquivo"]:
                return self.send_error(404)
            with open(sessao["arquivo"], "rb") as f:
                corpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(sessao["arquivo"])}"')
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        if url.path != "/eventos":
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        fila = queue.Queue(maxsize=2000)
        with trava:
            assinantes.append(fila)
        try:
            while True:
                try:
                    self.wfile.write(f"data: {fila.get(timeout=5)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with trava:
                assinantes.remove(fila)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--serial", required=True)
    p.add_argument("--http", type=int, default=8000)
    a = p.parse_args()
    try:  # reserva o HTTP antes de abrir a serial: uma segunda copia nao disputa a porta do Mega
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.http), Handler)
    except OSError:
        raise SystemExit(f"a porta {a.http} ja esta em uso: o painel provavelmente ja esta rodando em http://localhost:{a.http}/")
    srv.daemon_threads = True
    os.makedirs(PASTA_SESSOES, exist_ok=True)
    sessao["inicio"] = agora_ms()
    sessao["arquivo"] = os.path.join(PASTA_SESSOES, datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S") + ".log")
    sessao["f"] = open(sessao["arquivo"], "a", encoding="utf-8")
    registra(f"porta {a.serial} aberta (o Mega reseta ao abrir)", prefixo="> ponte: ")
    parar = threading.Event()
    t = threading.Thread(target=ler_serial, args=(a.serial, parar), daemon=True)
    t.start()
    print(f"painel: http://localhost:{a.http}/  (serial {a.serial}; registro {sessao['arquivo']})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        parar.set()
        t.join(timeout=1)
        srv.server_close()
        sessao["f"].close()
