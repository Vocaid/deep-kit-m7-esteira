"""Testes do hub registrador: parse, epocas, sessao simulada, leitura serial injetada, replay."""
import csv
import getpass
import hashlib
import io
import json
import os
import socket
import subprocess
import sys

import pytest

import registrador

DIR_SINAIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAB_SINAIS = "t_s,epoca,janela_mega,rpm,som_rms,som_pico,vib,score_mega,estado_mega"
CAB_EVENTOS = "t_s,epoca,texto"
CAB_ROTULOS = "t_s,epoca,janela_mega,rotulo"


def _sessao_unica(base):
    pastas = [p for p in os.listdir(base)]
    assert len(pastas) == 1
    return os.path.join(base, pastas[0])


def _simular(tmp_path, cenario, seed, nome="saida"):
    base = str(tmp_path / nome)
    assert registrador.main(["--simular", "--cenario", cenario, "--seed", str(seed), "--saida", base]) == 0
    return _sessao_unica(base)


def _ler_csv(caminho):
    with open(caminho, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- parse_linha
def test_parse_linha_valida():
    d = registrador.parse_linha("37,2040,62.5,93,5,0.4,NORMAL\r\n")
    assert d == {"janela": 37, "rpm": 2040.0, "som_rms": 62.5, "som_pico": 93.0, "vib": 5.0,
                 "score": 0.4, "estado": "NORMAL"}


def test_parse_linha_cabecalho_e_ignorado():
    assert registrador.parse_linha("janela,rpm,som_rms,som_pico,vib,score,estado") is None


def test_parse_linha_evento():
    assert registrador.parse_linha("# calibrado: c0 media=2000.0") == ("evento", "calibrado: c0 media=2000.0")
    assert registrador.parse_linha("#sem espaco") == ("evento", "sem espaco")


@pytest.mark.parametrize("lixo", ["", "   ", "\x00\xff", "== VOCAID DEEP ==", "1,2,3", "x,1,2,3,4,5,NORMAL",
                                  "1,2,3,4,5,6,7,8", "1,2000,60,90,5,0.0,TALVEZ", "12,20"])
def test_parse_linha_lixo_e_none(lixo):
    assert registrador.parse_linha(lixo) is None


@pytest.mark.parametrize("campo", ["abc", "", "nan", "NaN", "inf", "-inf"])
def test_parse_linha_campo_numerico_ruim_vira_none_nunca_nan_nem_texto(campo):
    d = registrador.parse_linha("5,%s,60,90,5,0.0,NORMAL" % campo)
    assert d["rpm"] is None
    assert d["som_rms"] == 60.0 and d["janela"] == 5


def test_parse_linha_todos_os_canais_ruins():
    d = registrador.parse_linha("5,a,b,c,d,e,CALIBRANDO")
    assert (d["rpm"], d["som_rms"], d["som_pico"], d["vib"], d["score"]) == (None,) * 5


# ---------------------------------------------------------------- Epocas
def test_epocas_vai_ate_40_e_reinicia():
    e = registrador.Epocas()
    assert [e.alimentar(j) for j in range(1, 41)] == [1] * 40
    assert e.alimentar(1) == 2
    assert e.alimentar(2) == 2


def test_epocas_janela_igual_a_anterior_tambem_reinicia():
    e = registrador.Epocas()
    e.alimentar(5)
    assert e.alimentar(5) == 2


def test_epocas_porta_reaberta_incrementa_uma_vez():
    e = registrador.Epocas()
    e.alimentar(10)
    assert e.porta_reaberta() == 2
    assert e.alimentar(1) == 2  # o reset da placa na reabertura nao conta de novo
    assert e.alimentar(2) == 2
    assert e.alimentar(1) == 3


# ---------------------------------------------------------------- sessao simulada
def test_simular_nulo_escreve_os_quatro_arquivos_com_cabecalhos_exatos(tmp_path):
    pasta = _simular(tmp_path, "nulo", 1)
    assert os.path.basename(pasta).endswith("-sim")
    assert sorted(os.listdir(pasta)) == ["eventos.csv", "manifesto.json", "rotulos.csv", "sinais.csv"]
    for nome, cab in (("sinais.csv", CAB_SINAIS), ("eventos.csv", CAB_EVENTOS), ("rotulos.csv", CAB_ROTULOS)):
        with open(os.path.join(pasta, nome)) as f:
            assert f.readline().rstrip("\n") == cab
    man = json.load(open(os.path.join(pasta, "manifesto.json")))
    assert man["simulado"] is True
    assert set(man) == {"simulado", "firmware_sha256", "versao_metricas", "criado_em"}
    assert man["firmware_sha256"] is None
    assert not any(r["estado_mega"] == "ALERTA" for r in _ler_csv(os.path.join(pasta, "sinais.csv")))


def test_nome_da_pasta_tem_data_e_hora(tmp_path):
    nome = os.path.basename(_simular(tmp_path, "nulo", 1))
    assert len(nome) == len("2026-11-08-1530-sim") and nome[4] == "-" and nome[10] == "-"


def test_completo_tem_todas_as_teclas_e_3_episodios_de_a_p_m(tmp_path):
    pasta = _simular(tmp_path, "completo", 7)
    rot = _ler_csv(os.path.join(pasta, "rotulos.csv"))
    teclas = [r["rotulo"] for r in rot]
    assert set(teclas) == {"n", "a", "p", "m", "s", "r", "x"}
    for k in "apm":
        assert teclas.count(k) >= 3
    assert teclas.count("s") == 1 and teclas.count("r") == 1


def test_mesma_semente_gera_sinais_csv_identico_byte_a_byte(tmp_path):
    a = _simular(tmp_path, "completo", 7, "um")
    b = _simular(tmp_path, "completo", 7, "dois")
    assert open(os.path.join(a, "sinais.csv"), "rb").read() == open(os.path.join(b, "sinais.csv"), "rb").read()
    c = _simular(tmp_path, "completo", 8, "tres")
    assert open(os.path.join(a, "sinais.csv"), "rb").read() != open(os.path.join(c, "sinais.csv"), "rb").read()


def test_nenhum_nan_nos_csvs_gravados(tmp_path):
    pasta = _simular(tmp_path, "completo", 7)
    for nome in ("sinais.csv", "rotulos.csv"):
        assert "nan" not in open(os.path.join(pasta, nome)).read().lower()
    for r in _ler_csv(os.path.join(pasta, "sinais.csv")):
        assert all(v != "" for v in r.values())


def test_latch_no_csv_gravado(tmp_path):
    pasta = _simular(tmp_path, "completo", 7)
    por_epoca = {}
    for r in _ler_csv(os.path.join(pasta, "sinais.csv")):
        por_epoca.setdefault(r["epoca"], []).append(r["estado_mega"])
    assert len(por_epoca) == 11
    for estados in por_epoca.values():
        i = estados.index("ALERTA")
        assert set(estados[i:]) == {"ALERTA"}


def test_manifesto_sem_hostname_nem_usuario(tmp_path):
    pasta = _simular(tmp_path, "nulo", 1)
    texto = open(os.path.join(pasta, "manifesto.json")).read()
    man = json.loads(texto)
    assert not any(k.lower() in ("hostname", "host", "user", "usuario", "username") for k in man)
    for proibido in (getpass.getuser(), socket.gethostname(), socket.gethostname().split(".")[0]):
        if len(proibido) >= 3:
            assert proibido not in texto


def test_manifesto_com_firmware_grava_sha256(tmp_path):
    fw = tmp_path / "fw.ino"
    fw.write_bytes(b"void setup(){}\n")
    base = str(tmp_path / "s")
    assert registrador.main(["--simular", "--cenario", "nulo", "--seed", "1", "--saida", base,
                             "--firmware", str(fw)]) == 0
    man = json.load(open(os.path.join(_sessao_unica(base), "manifesto.json")))
    assert man["firmware_sha256"] == hashlib.sha256(b"void setup(){}\n").hexdigest()


class _EnvSentinela(dict):
    def __init__(self):
        super().__init__(VOCAID_SEGREDO="nao-leia", PATH="/usr/bin")
        self.acessos = []

    def __getitem__(self, k):
        self.acessos.append(k)
        return super().__getitem__(k)

    def get(self, k, d=None):
        self.acessos.append(k)
        return super().get(k, d)

    def __contains__(self, k):
        self.acessos.append(k)
        return super().__contains__(k)

    def __iter__(self):
        self.acessos.append("*")
        return super().__iter__()

    def items(self):
        self.acessos.append("*")
        return super().items()

    def keys(self):
        self.acessos.append("*")
        return super().keys()

    def copy(self):
        self.acessos.append("*")
        return super().copy()


def test_nao_le_variaveis_de_ambiente(tmp_path, monkeypatch):
    sentinela = _EnvSentinela()
    monkeypatch.setattr(os, "environ", sentinela)
    _simular(tmp_path, "nulo", 1)
    # a stdlib (argparse: idioma, COLUMNS) consulta chaves soltas; o hub nunca varre o ambiente nem toca VOCAID_*
    assert "*" not in sentinela.acessos
    assert not any(str(a).upper().startswith("VOCAID") for a in sentinela.acessos)


def test_fonte_nao_toca_ambiente_nem_rede():
    for nome in ("registrador.py", "simulador.py"):
        fonte = open(os.path.join(DIR_SINAIS, nome)).read()
        for proibido in ("environ", "getenv", "VOCAID", "socket", "urllib", "http.client", "requests",
                         "gethostname", "getpass", "platform.node"):
            assert proibido not in fonte, (nome, proibido)


def test_cli_como_script_com_python_isolado(tmp_path):
    base = str(tmp_path / "cli")
    r = subprocess.run([sys.executable, "-I", os.path.join(DIR_SINAIS, "registrador.py"), "--simular",
                        "--cenario", "nulo", "--seed", "1", "--saida", base],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert os.path.exists(os.path.join(_sessao_unica(base), "sinais.csv"))


def test_cli_exige_um_modo(tmp_path):
    with pytest.raises(SystemExit) as e:
        registrador.main([])
    assert e.value.code == 2


# ---------------------------------------------------------------- leitura serial injetada (sem hardware)
class _Relogio:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 1.0
        return self.t


def _gravar(tmp_path, linhas, teclas=None):
    s = registrador.Sessao(str(tmp_path / "ao-vivo"), simulado=False)
    registrador.gravar_linhas(linhas, s, teclas=teclas, relogio=_Relogio())
    s.fechar()
    d = str(tmp_path / "ao-vivo")
    return _ler_csv(d + "/sinais.csv"), _ler_csv(d + "/eventos.csv"), _ler_csv(d + "/rotulos.csv"), d


def test_gravar_linhas_serial_falsa_epocas_eventos_e_lixo(tmp_path):
    linhas = ["== VOCAID DEEP ==", "# metodo: z-score", "janela,rpm,som_rms,som_pico,vib,score,estado",
              "1,2000,60.0,90,5,0.0,AQUECENDO", "\x00lixo\xff", "2,2000,60.0,90,5,0.0,AQUECENDO",
              "# calibrado: ok", "3,abc,60.0,90,5,0.0,AQUECENDO",
              "1,2000,60.0,90,5,0.0,AQUECENDO",           # janela voltou: epoca 2
              registrador.REABERTA,                       # porta reaberta: epoca 3
              "1,2000,60.0,90,5,0.0,AQUECENDO"]
    sinais, eventos, _, _ = _gravar(tmp_path, linhas)
    assert [r["epoca"] for r in sinais] == ["1", "1", "1", "2", "3"]
    assert [r["janela_mega"] for r in sinais] == ["1", "2", "3", "1", "1"]
    assert sinais[2]["rpm"] == ""  # campo ruim vira celula vazia, nunca "nan" nem "abc"
    assert [(e["epoca"], e["texto"]) for e in eventos] == [("1", "metodo: z-score"), ("1", "calibrado: ok")]


def test_gravar_linhas_rotulos_teclas_valem_com_ultima_janela(tmp_path):
    fila = iter([["n"], [], ["a", "z"], [], ["x"], ["q"]])
    linhas = ["1,2000,60.0,90,5,0.0,AQUECENDO", "2,2000,60.0,90,5,0.0,AQUECENDO",
              "3,2000,60.0,90,5,0.0,AQUECENDO", "4,2000,60.0,90,5,0.0,AQUECENDO",
              "5,2000,60.0,90,5,0.0,AQUECENDO", "6,2000,60.0,90,5,0.0,AQUECENDO",
              "7,2000,60.0,90,5,0.0,AQUECENDO"]  # o 'q' na 7a volta encerra antes de gravar mais
    sinais, _, rotulos, _ = _gravar(tmp_path, linhas, teclas=lambda: next(fila, []))
    assert [(r["rotulo"], r["janela_mega"]) for r in rotulos] == [("n", "1"), ("a", "3"), ("x", "5")]
    assert [r["epoca"] for r in rotulos] == ["1", "1", "1"]  # 'z' nao e tecla valida
    assert len(sinais) == 6  # parou no 'q'


def test_gravar_linhas_tick_vazio_consulta_teclas_sem_gravar(tmp_path):
    fila = iter([["n"], ["q"]])
    sinais, _, rotulos, _ = _gravar(tmp_path, ["", ""], teclas=lambda: next(fila, []))
    assert sinais == [] and [r["rotulo"] for r in rotulos] == ["n"]
    assert rotulos[0]["janela_mega"] == ""  # nenhuma janela vista ainda


def test_rotulos_arquivo(tmp_path):
    p = tmp_path / "rot.csv"
    p.write_text("t_s,rotulo\n2.0,n\n5.5,a\n\n7.0,x\n9.0,q\n")
    ra = registrador.RotulosArquivo(str(p))
    assert ra.pendentes(1.0) == []
    assert ra.pendentes(5.5) == ["n", "a"]
    assert ra.pendentes(6.0) == []
    assert ra.pendentes(100.0) == ["x", "q"]
    assert ra.pendentes(200.0) == []


# ---------------------------------------------------------------- replay
def test_replay_reemite_linhas_do_mega_e_reanalisa_igual(tmp_path):
    pasta = _simular(tmp_path, "completo", 7)
    saida = io.StringIO()
    dormidas = []
    registrador.replay(pasta, velocidade=10.0, saida=saida, dormir=dormidas.append)
    linhas = saida.getvalue().splitlines()
    assert linhas[0] == "janela,rpm,som_rms,som_pico,vib,score,estado"
    sinais = _ler_csv(os.path.join(pasta, "sinais.csv"))
    parseadas = [registrador.parse_linha(l) for l in linhas]
    dados = [p for p in parseadas if isinstance(p, dict)]
    eventos = [p for p in parseadas if isinstance(p, tuple)]
    assert len(dados) == len(sinais)
    assert [d["janela"] for d in dados] == [int(r["janela_mega"]) for r in sinais]
    assert [d["estado"] for d in dados] == [r["estado_mega"] for r in sinais]
    assert [d["rpm"] for d in dados] == [float(r["rpm"]) for r in sinais]
    assert len(eventos) == len(_ler_csv(os.path.join(pasta, "eventos.csv")))
    # velocidade 10x: 1 s de sessao vira 0,1 s de espera
    assert abs(dormidas[0] - 0.1) < 1e-9
    assert abs(sum(dormidas) - (float(sinais[-1]["t_s"]) - float(sinais[0]["t_s"])) / 10) < 1e-6


def test_replay_cli_escreve_no_stdout(tmp_path, capsys):
    pasta = _simular(tmp_path, "nulo", 1)
    capsys.readouterr()
    assert registrador.main(["--replay", pasta, "--velocidade", "100000"]) == 0
    saida = capsys.readouterr().out.splitlines()
    assert saida[0].startswith("janela,rpm") and len(saida) > 100


# ---------------------------------------------------------------- correcoes da revisao
def test_tecla_antes_da_primeira_janela_da_nova_epoca_tem_janela_vazia(tmp_path):
    linhas = ["1,2000,60.0,90,5,0.0,AQUECENDO", "2,2000,60.0,90,5,0.0,AQUECENDO", registrador.REABERTA,
              "1,2000,60.0,90,5,0.0,AQUECENDO"]
    fila = iter([[], [], ["a"], []])  # a tecla chega no tick da REABERTA, antes de qualquer janela nova
    sinais, _, rotulos, _ = _gravar(tmp_path, linhas, teclas=lambda: next(fila, []))
    assert [(r["rotulo"], r["epoca"], r["janela_mega"]) for r in rotulos] == [("a", "2", "")]
    assert [r["epoca"] for r in sinais] == ["1", "1", "2"]


def test_linha_partida_em_duas_leituras_vira_uma_janela_sem_lixo(tmp_path):
    leituras = [b"1,2000,60", b"", b".0,90,5,0.0,AQUECENDO\r\n2,2000,", b"60.0,90,5,0.0,AQUECENDO\n", b""]
    linhas = list(registrador.linhas_de_leituras(leituras))
    assert [l for l in linhas if l] == ["1,2000,60.0,90,5,0.0,AQUECENDO\r", "2,2000,60.0,90,5,0.0,AQUECENDO"]
    assert all(registrador.parse_linha(l) is not None for l in linhas if l)
    sinais, eventos, _, _ = _gravar(tmp_path, linhas)
    assert [r["janela_mega"] for r in sinais] == ["1", "2"] and eventos == []


def test_buffer_limitado_descarta_ruido_sem_fim_de_linha(tmp_path):
    buf = registrador.BufferLinhas()
    saida = []
    for _ in range(10):  # 10 x 1000 bytes sem \n
        saida += buf.alimentar(b"x" * 1000)
        assert len(buf._resto) <= registrador.LIMITE_LINHA
    assert buf.descartes == 2 and saida == [registrador.TEXTO_DESCARTE] * 2
    saida += buf.alimentar(b"1,2000,60.0,90,5,0.0,AQUECENDO\n")
    sinais, eventos, _, _ = _gravar(tmp_path, saida)
    assert [r["janela_mega"] for r in sinais] == ["1"]
    assert len(eventos) == 2 and "descartada" in eventos[0]["texto"]


# ---------------------------------------------------------------- o terminal mostra o que o registrador ve
def test_gravar_linhas_imprime_toda_linha_do_mega_e_uma_linha_por_tecla(tmp_path, capsys):
    fila = iter([[], [], ["n"], [], ["a", "z"], [], [], ["x"], ["q"]])
    linhas = ["AUTO-TESTE: 13/13 -> PASS", "# calibrado: ok", "1,2000,60.0,90,5,0.0,AQUECENDO", "\x00lixo",
              "2,2000,60.0,90,5,0.0,AQUECENDO",
              "1,2000,60.0,90,5,0.0,AQUECENDO",            # reset: epoca 2
              "# rele A fechado", "2,2000,60.0,90,5,0.0,AQUECENDO", "3,2000,60.0,90,5,0.0,AQUECENDO"]
    _gravar(tmp_path, linhas, teclas=lambda: next(fila, []))
    saida = capsys.readouterr().out.splitlines()
    assert saida[:6] == ["AUTO-TESTE: 13/13 -> PASS", "# calibrado: ok", "1,2000,60.0,90,5,0.0,AQUECENDO",
                         "rotulo n -> epoca 1 apos janela 1", "?lixo", "2,2000,60.0,90,5,0.0,AQUECENDO"]
    assert "rotulo n -> epoca 1 apos janela 1" in saida and "rotulo a -> epoca 1 apos janela 2" in saida
    assert "rotulo x -> epoca 2 apos janela 2" in saida
    assert "# calibrado: ok" in saida and "# rele A fechado" in saida
    assert saida.count("1,2000,60.0,90,5,0.0,AQUECENDO") == 2
    assert not any(l.startswith("rotulo z") for l in saida)


def test_tecla_antes_de_qualquer_janela_imprime_traco(tmp_path, capsys):
    fila = iter([["n"], ["q"]])
    _gravar(tmp_path, ["", ""], teclas=lambda: next(fila, []))
    assert capsys.readouterr().out.splitlines() == ["rotulo n -> epoca 1 apos janela -"]


def test_restauracao_do_terminal_continua_valendo_com_a_impressao(monkeypatch):
    """_TeclasCbreak restaura o termios ao sair mesmo se o laco levantar."""
    import termios
    chamadas = []
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: "antigo")
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, quando, attrs: chamadas.append(attrs))
    import tty
    monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"fileno": lambda self: 0})())
    with pytest.raises(RuntimeError):
        with registrador._TeclasCbreak():
            registrador.gravar_linhas(iter(["1,2000,60.0,90,5,0.0,AQUECENDO"]), type("F", (), {
                "sinal": lambda *a: (_ for _ in ()).throw(RuntimeError("falha")), "evento": lambda *a: None,
                "rotulo": lambda *a: None})())
    assert chamadas == ["antigo"]
