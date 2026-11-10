"""Registrador (hub) da bancada M7: unico ponto de entrada dos sinais.

Modos (exatamente um):
  --serial <porta> [--baud 115200] [--rotulos-arquivo f]   le o Mega por pyserial; teclas n/a/p/m/c/s/r/x rotulam, q encerra
  --simular [--cenario completo|nulo] [--seed N]           sessao simulada, sem hardware
  --replay <sessao/> [--velocidade 10]                     re-emite as linhas do Mega no stdout

Escreve sinais/sessoes/<AAAA-MM-DD-HHMM>[-sim]/ com sinais.csv, eventos.csv, rotulos.csv, manifesto.json.
Sem rede, sem variaveis de ambiente, sem nome de maquina ou de usuario. Texto de saida em ASCII.
"""
import os
import sys

# Com `python -I` o diretorio deste script nao entra no sys.path: inserimos explicitamente.
DIR_SINAIS = os.path.dirname(os.path.abspath(__file__))
if DIR_SINAIS not in sys.path:
    sys.path.insert(0, DIR_SINAIS)

import argparse  # noqa: E402
import csv  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402

import metricas  # noqa: E402
import simulador  # noqa: E402

CAB_SINAIS = ("t_s", "epoca", "janela_mega", "rpm", "som_rms", "som_pico", "vib", "score_mega", "estado_mega")
CAB_EVENTOS = ("t_s", "epoca", "texto")
CAB_ROTULOS = ("t_s", "epoca", "janela_mega", "rotulo")
CAB_MEGA = "janela,rpm,som_rms,som_pico,vib,score,estado"
ESTADOS = ("AQUECENDO", "CALIBRANDO", "NORMAL", "ALERTA", "SUSPEITA")
TECLAS_ROTULO = "napmcsrx"
BAUD_PADRAO = 115200
REABERTA = object()  # marca, no fluxo de linhas, que a porta foi reaberta (nova epoca)


# ---------------------------------------------------------------- linha do Mega
def _numero(texto):
    """Campo numerico -> float, ou None se vazio, ilegivel, NaN ou infinito. Nunca NaN, nunca texto."""
    try:
        v = float(texto)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse_linha(s):
    """`janela,rpm,som_rms,som_pico,vib,score,estado` -> dict; `# ...` -> ("evento", texto);
    cabecalho, linha vazia e lixo -> None. Campo numerico ilegivel vira None."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if s.startswith("#"):
        return ("evento", s.lstrip("#").strip())
    if s.startswith("janela"):
        return None
    campos = [c.strip() for c in s.split(",")]
    if len(campos) != 7 or campos[6] not in ESTADOS:
        return None
    try:
        janela = int(campos[0])
    except ValueError:
        return None
    if janela < 0:
        return None
    rpm, som_rms, som_pico, vib, score = (_numero(c) for c in campos[1:6])
    return {"janela": janela, "rpm": rpm, "som_rms": som_rms, "som_pico": som_pico, "vib": vib,
            "score": score, "estado": campos[6]}


class Epocas:
    """Epoca = bloco entre resets da placa: sobe quando `janela` do Mega nao cresce ou quando a porta reabre."""

    def __init__(self):
        self.epoca = 1
        self._anterior = None

    def alimentar(self, janela_mega):
        if self._anterior is not None and janela_mega <= self._anterior:
            self.epoca += 1
        self._anterior = janela_mega
        return self.epoca

    def porta_reaberta(self):
        self.epoca += 1
        self._anterior = None  # o proximo 'janela 1' ja pertence a nova epoca
        return self.epoca


# ---------------------------------------------------------------- sessao em disco
def _fmt(v):
    """None -> celula vazia (nunca NaN); inteiro exato sem ponto; senao ate 3 casas."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        v = float(v)
        if v == int(v):
            return str(int(v))
        return ("%.3f" % v).rstrip("0").rstrip(".")
    return str(v)


def _fmt_t(t):
    return "%.1f" % t


class Sessao:
    """Pasta de sessao. Cada escrita e gravada na hora (flush): o ao-vivo sobrevive a um Ctrl-C."""

    def __init__(self, pasta, simulado, firmware_sha256=None):
        os.makedirs(pasta, exist_ok=False)
        self.pasta = pasta
        self._abertos = []
        self._w = {}
        for nome, cab in (("sinais", CAB_SINAIS), ("eventos", CAB_EVENTOS), ("rotulos", CAB_ROTULOS)):
            f = open(os.path.join(pasta, nome + ".csv"), "w", newline="")
            self._abertos.append(f)
            w = csv.writer(f, lineterminator="\n")
            w.writerow(cab)
            f.flush()
            self._w[nome] = w
        self.escrever_manifesto(simulado, firmware_sha256)

    def escrever_manifesto(self, simulado, firmware_sha256):
        man = {
            "simulado": bool(simulado),
            "firmware_sha256": firmware_sha256,
            "versao_metricas": _versao_metricas(),
            "criado_em": datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        }
        with open(os.path.join(self.pasta, "manifesto.json"), "w") as f:
            json.dump(man, f, indent=2)
            f.write("\n")

    def _linha(self, nome, valores):
        self._w[nome].writerow(valores)
        self._abertos[("sinais", "eventos", "rotulos").index(nome)].flush()

    def sinal(self, t, epoca, d):
        self._linha("sinais", (_fmt_t(t), epoca, d["janela"], _fmt(d["rpm"]), _fmt(d["som_rms"]),
                               _fmt(d["som_pico"]), _fmt(d["vib"]), _fmt(d["score"]), d["estado"]))

    def evento(self, t, epoca, texto):
        self._linha("eventos", (_fmt_t(t), epoca, texto))

    def rotulo(self, t, epoca, janela, rotulo):
        # janela_mega = ultima janela vista quando a tecla foi pressionada; o rotulo vale para janelas com
        # janela_mega > este valor na mesma epoca; vazio = nenhuma janela ainda nesta epoca (vale desde a primeira).
        self._linha("rotulos", (_fmt_t(t), epoca, "" if janela is None else janela, rotulo))

    def fechar(self):
        for f in self._abertos:
            f.close()


def _versao_metricas():
    """Identifica a versao de metricas.py pelos primeiros 12 hex do sha256 do arquivo."""
    with open(metricas.__file__, "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()[:12]


def _sha256_arquivo(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _pasta_nova(base, simulado):
    agora = datetime.datetime.now()
    nome = agora.strftime("%Y-%m-%d-%H%M") + ("-sim" if simulado else "")
    pasta = os.path.join(base, nome)
    n = 2
    while os.path.exists(pasta):
        pasta = os.path.join(base, "%s-%d" % (nome, n))
        n += 1
    os.makedirs(base, exist_ok=True)
    return pasta


# ---------------------------------------------------------------- gravacao (serial e injetada)
class RotulosArquivo:
    """Rotulos sem TTY: arquivo `t_s,rotulo` (cabecalho opcional). `pendentes(t)` devolve as teclas
    cujo t_s ja passou, uma vez cada."""

    def __init__(self, caminho):
        itens = []
        with open(caminho, newline="") as f:
            for linha in csv.reader(f):
                if len(linha) < 2:
                    continue
                t = _numero(linha[0])
                if t is None:
                    continue
                itens.append((t, linha[1].strip()))
        self._itens = sorted(itens, key=lambda x: x[0])
        self._i = 0

    def pendentes(self, t):
        saida = []
        while self._i < len(self._itens) and self._itens[self._i][0] <= t:
            saida.append(self._itens[self._i][1])
            self._i += 1
        return saida


LIMITE_LINHA = 4096  # bytes sem `\n` acima disto sao ruido: descarta em vez de crescer sem fim
TEXTO_DESCARTE = "# linha descartada: ruido sem fim de linha"


class BufferLinhas:
    """Junta bytes ate o `\n`: um timeout no meio da linha nunca entrega fragmentos."""

    def __init__(self):
        self._resto = b""
        self.descartes = 0

    def alimentar(self, bruto):
        """Recebe bytes (possivelmente parciais ou vazios); devolve as linhas completas decodificadas."""
        self._resto += bruto
        saida = []
        while b"\n" in self._resto:
            linha, self._resto = self._resto.split(b"\n", 1)
            saida.append(linha.decode("utf-8", errors="replace"))
        if len(self._resto) > LIMITE_LINHA:
            self._resto = b""
            self.descartes += 1
            saida.append(TEXTO_DESCARTE)  # vira evento na sessao pelo caminho normal
        return saida

    def limpar(self):
        self._resto = b""


def linhas_de_leituras(leituras):
    """Iteravel de leituras (bytes, b"" = timeout) -> linhas completas; `""` quando nada completou (tick ocioso)."""
    buf = BufferLinhas()
    for bruto in leituras:
        completas = buf.alimentar(bruto)
        if completas:
            yield from completas
        else:
            yield ""


def _imprimivel(linha):
    """Linha do Mega para o terminal: sem fim de linha e sem caractere de controle (lixo da serial vira `?`)."""
    return "".join(c if c.isprintable() else "?" for c in linha.rstrip("\r\n"))


def gravar_linhas(linhas, sessao, teclas=None, relogio=time.monotonic, saida=None):
    """Consome qualquer iteravel de linhas (serial real ou lista nos testes) e grava a sessao.
    Convencao de rotulos.csv: janela_mega = ultima janela vista quando a tecla foi pressionada; o rotulo vale
    para janelas com janela_mega > este valor na mesma epoca; vazio = nenhuma janela ainda nesta epoca
    (vale desde a primeira).
    `""` e um tick ocioso (so consulta as teclas); `REABERTA` abre nova epoca; `teclas()` devolve as
    teclas pendentes (lista de 1 caractere). A tecla `q` encerra.
    O registrador e' dono da porta serial: ele mostra no terminal (`saida`, stdout) toda linha do Mega (dado e `#`)
    e uma linha por tecla de rotulo (`rotulo X -> epoca E apos janela J`), para o operador ver em que epoca caiu."""
    saida = saida or sys.stdout
    epocas = Epocas()
    t0 = relogio()
    ultima_janela = None
    for linha in linhas:
        t = relogio() - t0
        if linha is REABERTA:
            epocas.porta_reaberta()
            ultima_janela = None  # nova epoca: nenhuma janela vista ainda
        else:
            if linha.strip():
                print(_imprimivel(linha), file=saida, flush=True)
            p = parse_linha(linha)
            if isinstance(p, dict):
                ep = epocas.alimentar(p["janela"])
                ultima_janela = p["janela"]
                sessao.sinal(t, ep, p)
            elif isinstance(p, tuple):
                sessao.evento(t, epocas.epoca, p[1])
        sair = False
        for tecla in (teclas() if teclas else []):
            if tecla == "q":
                sair = True
            elif tecla in TECLAS_ROTULO:
                sessao.rotulo(t, epocas.epoca, ultima_janela, tecla)
                print("rotulo %s -> epoca %d apos janela %s" % (
                    tecla, epocas.epoca, "-" if ultima_janela is None else ultima_janela), file=saida, flush=True)
        if sair:
            break


def linhas_serial(porta, baud=BAUD_PADRAO, pausa_reabrir=1.0):
    """Gera linhas do Mega por pyserial (importado so aqui). Timeout curto: devolve "" em silencio para
    o laco consultar as teclas. Se a porta cair, reabre e sinaliza REABERTA."""
    import serial  # lazy: so o modo --serial precisa de pyserial

    def abrir():
        return serial.Serial(porta, baud, timeout=0.2)

    conexao = abrir()
    buf = BufferLinhas()
    try:
        while True:
            try:
                bruto = conexao.readline()
            except (serial.SerialException, OSError):
                conexao.close()
                buf.limpar()
                while True:
                    time.sleep(pausa_reabrir)
                    try:
                        conexao = abrir()
                        break
                    except (serial.SerialException, OSError):
                        continue
                yield REABERTA
                continue
            completas = buf.alimentar(bruto)
            if completas:
                yield from completas
            else:
                yield ""
    finally:
        conexao.close()


class _TeclasCbreak:
    """Teclas do stdin em modo cbreak (so em TTY): devolve os caracteres pendentes sem bloquear."""

    def __enter__(self):
        import termios
        import tty
        self._termios = termios
        self._fd = sys.stdin.fileno()
        self._antigo = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc):
        self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._antigo)

    def __call__(self):
        import select
        saida = []
        while select.select([sys.stdin], [], [], 0)[0]:
            c = os.read(self._fd, 1).decode("ascii", errors="ignore")
            if not c:
                break
            saida.append(c)
        return saida


# ---------------------------------------------------------------- simulacao e replay
def gravar_simulado(base, cenario, seed, firmware_sha256=None):
    sim = simulador.simular(cenario, seed)
    sessao = Sessao(_pasta_nova(base, True), simulado=True, firmware_sha256=firmware_sha256)
    try:
        for s in sim["sinais"]:
            sessao.sinal(s["t_s"], s["epoca"], {"janela": s["janela_mega"], "rpm": s["rpm"],
                         "som_rms": s["som_rms"], "som_pico": s["som_pico"], "vib": s["vib"],
                         "score": s["score_mega"], "estado": s["estado_mega"]})
        for e in sim["eventos"]:
            sessao.evento(e["t_s"], e["epoca"], e["texto"])
        for r in sim["rotulos"]:
            sessao.rotulo(r["t_s"], r["epoca"], r["janela_mega"], r["rotulo"])
    finally:
        sessao.fechar()
    return sessao.pasta


def _ler(caminho):
    with open(caminho, newline="") as f:
        return list(csv.DictReader(f))


def replay(pasta, velocidade=10.0, saida=None, dormir=time.sleep):
    """Re-emite no formato do Mega: cabecalho, e para cada janela as linhas `# ...` seguidas da linha de dados
    (na ordem do firmware: narracao antes). Espera dt/velocidade entre instantes diferentes."""
    saida = saida or sys.stdout
    itens = []  # (t, ordem, texto): narracao (0) antes do dado (1) no mesmo t
    for e in _ler(os.path.join(pasta, "eventos.csv")):
        itens.append((float(e["t_s"]), 0, "# " + e["texto"]))
    for r in _ler(os.path.join(pasta, "sinais.csv")):
        score = _numero(r["score_mega"])
        itens.append((float(r["t_s"]), 1, ",".join([
            r["janela_mega"], r["rpm"], r["som_rms"], r["som_pico"], r["vib"],
            "" if score is None else "%.1f" % score, r["estado_mega"]])))
    itens.sort(key=lambda x: (x[0], x[1]))
    saida.write(CAB_MEGA + "\n")
    anterior = itens[0][0] if itens else 0.0
    for t, _, texto in itens:
        if t > anterior:
            dormir((t - anterior) / velocidade)
            anterior = t
        saida.write(texto + "\n")
        saida.flush()


# ---------------------------------------------------------------- CLI
def _parser():
    p = argparse.ArgumentParser(prog="registrador.py", description=__doc__.split("\n")[0])
    modo = p.add_mutually_exclusive_group(required=True)
    modo.add_argument("--serial", metavar="PORTA")
    modo.add_argument("--simular", action="store_true")
    modo.add_argument("--replay", metavar="SESSAO")
    p.add_argument("--baud", type=int, default=BAUD_PADRAO)
    p.add_argument("--rotulos-arquivo", metavar="ARQ")
    p.add_argument("--cenario", choices=("completo", "nulo"), default="completo")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--velocidade", type=float, default=10.0)
    p.add_argument("--firmware", metavar="INO", help="arquivo .ino cujo sha256 vai no manifesto")
    p.add_argument("--saida", default=os.path.join(DIR_SINAIS, "sessoes"), help="pasta base das sessoes")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    sha = _sha256_arquivo(args.firmware) if args.firmware else None
    if args.replay:
        replay(args.replay, velocidade=args.velocidade)
        return 0
    if args.simular:
        pasta = gravar_simulado(args.saida, args.cenario, args.seed, sha)
        print("sessao simulada gravada em", pasta)
        return 0
    return _modo_serial(args, sha)


def _modo_serial(args, sha):  # pragma: no cover - precisa de hardware
    sessao = Sessao(_pasta_nova(args.saida, False), simulado=False, firmware_sha256=sha)
    print("gravando em", sessao.pasta, "(q encerra). Nao abra o Serial Monitor do Arduino: esta janela mostra as linhas do Mega.",
          file=sys.stderr)
    t0 = time.monotonic()
    try:
        if args.rotulos_arquivo:
            arq = RotulosArquivo(args.rotulos_arquivo)
            gravar_linhas(linhas_serial(args.serial, args.baud), sessao,
                          teclas=lambda: arq.pendentes(time.monotonic() - t0))
        elif sys.stdin.isatty():
            with _TeclasCbreak() as teclas:
                gravar_linhas(linhas_serial(args.serial, args.baud), sessao, teclas=teclas)
        else:
            print("aviso: stdin nao e um terminal e falta --rotulos-arquivo: gravando sem rotulos", file=sys.stderr)
            gravar_linhas(linhas_serial(args.serial, args.baud), sessao)
    except KeyboardInterrupt:
        pass
    finally:
        sessao.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
