"""O notebook e' gerado para qualquer sessao e executa de ponta a ponta: na fixture, e numa sessao reduzida sem
p, s, r (e, no segundo caso, declarada real) onde nada pode levantar e o texto so' do simulador some."""
import csv
import json
import os
import shutil
import subprocess
import sys

import pytest

nbformat = pytest.importorskip("nbformat")
pytest.importorskip("nbconvert")
from nbconvert.preprocessors import ExecutePreprocessor  # noqa: E402

DIR_SINAIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GERAR = os.path.join(DIR_SINAIS, "notebook", "gerar_notebook.py")
EXEMPLO = os.path.join(DIR_SINAIS, "sessoes", "exemplo-simulado")


def _executar(sessao, destino):
    r = subprocess.run([sys.executable, "-I", GERAR, str(sessao), "--saida", str(destino / "nb.ipynb")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    nb = nbformat.read(str(destino / "nb.ipynb"), as_version=4)
    ExecutePreprocessor(timeout=300, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(destino)}})
    return nb


def _saida(nb):
    txt = []
    for c in nb.cells:
        for o in c.get("outputs", []):
            if o.output_type == "stream":
                txt.append(o.text)
            elif o.output_type in ("display_data", "execute_result"):
                txt.append(o.data.get("text/markdown", "") or o.data.get("text/plain", ""))
    return "\n".join(txt)


def _reduzida(tmp_path, simulado, manter=(1, 3)):
    """Fixture so com as epocas 1 (a) e 3 (m): sem p, sem s, sem r."""
    pasta = tmp_path / "reduzida"
    pasta.mkdir()
    for nome in ("sinais.csv", "rotulos.csv", "eventos.csv"):
        with open(os.path.join(EXEMPLO, nome), newline="") as f:
            lin = list(csv.reader(f))
        col = lin[0].index("epoca")
        with open(pasta / nome, "w", newline="") as f:
            csv.writer(f).writerows([lin[0]] + [x for x in lin[1:] if int(x[col]) in manter])
    man = json.load(open(os.path.join(EXEMPLO, "manifesto.json")))
    man["simulado"] = simulado
    (pasta / "manifesto.json").write_text(json.dumps(man))
    return pasta


def test_notebook_executa_na_fixture(tmp_path):
    nb = _executar(EXEMPLO, tmp_path)
    t = _saida(nb)
    assert "simulado: True" in t and "SIMULADA" in t
    assert "Traceback" not in t and "esta sessão não tem" not in t
    assert "EVENTO ESPERADO (parada pelo app, s)  | época 10" in t


@pytest.mark.parametrize("simulado", [True, False])
def test_notebook_executa_em_sessao_sem_p_s_r(tmp_path, simulado):
    nb = _executar(_reduzida(tmp_path, simulado), tmp_path)
    t = _saida(nb)
    assert "simulado: %s" % simulado in t
    assert "esta sessão não tem p" in t and "esta sessão não tem s" in t and "esta sessão não tem `r`" in t
    assert "ANOMALIA (atrito, a)  | época 1" in t        # o que existe continua saindo, da primeira epoca que tem a classe
    assert "INCONSISTÊNCIA (microfone tampado, m)  | época 3" in t
    assert ("SIMULADA" in t) is simulado
    assert ("Sessão REAL" in t) is (not simulado)
    assert ("simulador sem atraso humano" in t) is simulado   # prosa so' do simulador
    assert "Traceback" not in t


def test_gerar_aceita_o_nome_relativo_a_sinais_e_rejeita_pasta_invalida(tmp_path):
    r = subprocess.run([sys.executable, "-I", GERAR, "sessoes/exemplo-simulado", "--saida", str(tmp_path / "x.ipynb")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-I", GERAR, str(tmp_path / "nao-existe"), "--saida", str(tmp_path / "y.ipynb")],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "sessao invalida" in r.stderr
