"""Testes de avaliar.py. Os de fumaca usam sessoes SIMULADAS: sao smoke tests, nunca prova.
Expectativas vem das regras (brief da S3), nao de rodar o codigo."""
import csv
import json
import os
import subprocess
import sys

import pytest

import avaliar
import registrador

DIR_SINAIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVALIAR = os.path.join(DIR_SINAIS, "avaliar.py")
EXEMPLO = os.path.join(DIR_SINAIS, "sessoes", "exemplo-simulado")


def _rodar(sessao, *extra):
    r = subprocess.run([sys.executable, "-I", AVALIAR, str(sessao), *extra], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _simular(tmp_path, cenario, seed=7):
    return registrador.gravar_simulado(str(tmp_path), cenario, seed)


def _jsonl(sessao):
    with open(os.path.join(sessao, "detectores.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def _json(sessao):
    with open(os.path.join(sessao, "avaliacao.json"), encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------ expansao de rotulos
def _jan(*jms):
    return [{"janela_mega": j} for j in jms]


def test_expandir_rotulo_vale_so_para_janelas_depois_da_tecla():
    # tecla n na janela 33 -> vale a partir da 34; tecla a na 48 -> vale a partir da 49
    janelas = _jan(*range(30, 52))
    r = avaliar.expandir_rotulos(janelas, [(33, "n"), (48, "a")])
    por = dict(zip(range(30, 52), r))
    assert por[33] is None and por[30] is None
    assert por[34] == "n" and por[48] == "n"
    assert por[49] == "a" and por[51] == "a"


def test_expandir_janela_vazia_vale_desde_a_primeira_janela_da_epoca():
    r = avaliar.expandir_rotulos(_jan(1, 2, 3), [(None, "s")])
    assert r == ["s", "s", "s"]


def test_expandir_rotulo_nao_atravessa_a_epoca():
    ep1 = avaliar.expandir_rotulos(_jan(1, 2, 3), [(1, "x")])
    ep2 = avaliar.expandir_rotulos(_jan(1, 2, 3), [])  # epoca 2 sem tecla ainda
    assert ep1 == [None, "x", "x"]
    assert ep2 == [None, None, None]


def test_epocas_do_arquivo_nao_herdam_rotulo_da_anterior(tmp_path):
    sessao = _sessao_manual(tmp_path, epocas=2, rot=[(1, 33, "n"), (1, 40, "a")])  # epoca 2 sem tecla
    rots = avaliar.carregar(sessao)["rotulos_por_janela"]
    assert rots[0][-1] == "a"
    assert all(x is None for x in rots[1])


# ------------------------------------------------------------ sessoes feitas a mao
def _sessao_manual(tmp_path, epocas=1, rot=(), n=60, rpm=None, nome="manual", som=None, estado=None):
    pasta = tmp_path / nome
    pasta.mkdir()
    with open(pasta / "sinais.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(registrador.CAB_SINAIS)
        for e in range(1, epocas + 1):
            for j in range(1, n + 1):
                v = (j % 3)
                r = rpm(e, j) if rpm else 2000 + 60 * (v - 1)
                sm = som(e, j) if som else 60 + v
                est = estado(e, j) if estado else "NORMAL"
                w.writerow([float(j + (e - 1) * n), e, j, "" if r is None else r, sm, 90 + v, 5 + (j % 2), 0, est])
    with open(pasta / "rotulos.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(registrador.CAB_ROTULOS)
        for e, jm, r in rot:
            w.writerow([0.0, e, "" if jm is None else jm, r])
    (pasta / "eventos.csv").write_text("t_s,epoca,texto\n")
    (pasta / "manifesto.json").write_text(json.dumps({"simulado": True}))
    return str(pasta)


def test_baseline_com_menos_de_15_janelas_marca_insuficiente_e_ia_nao_avaliou(tmp_path):
    # n de 34 a 45 (12 janelas) e depois a
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 45, "a")])
    _rodar(sessao)
    linhas = _jsonl(sessao)
    assert all(l["ia"]["avaliada"] is False and l["ia"]["disparou"] is False for l in linhas)
    assert all(l["classe_final"] is None for l in linhas)
    assert _json(sessao)["epocas"][0]["baseline_insuficiente"] is True


# ------------------------------------------------------------ C1: epoca sem n e IA que nao avaliou
def test_epoca_sem_tecla_n_ainda_tem_baseline(tmp_path):
    """Janela sem rotulo depois da calibracao conta como normal: o operador que nunca apertou n nao desliga a IA."""
    sessao = _sessao_manual(tmp_path, rot=[(1, 50, "a")])
    _rodar(sessao)
    ep = _json(sessao)["epocas"][0]
    assert ep["baseline_n"] == 17 and ep["baseline_ate_janela"] == 50 and not ep["baseline_insuficiente"]
    por = {l["janela_mega"]: l for l in _jsonl(sessao)}
    assert por[10]["ia"] is None and por[51]["ia"]["avaliada"] is True


def test_rotulo_nao_n_interrompe_o_baseline_mesmo_com_janelas_sem_rotulo_antes(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 40, "s")])  # 34..40 sem rotulo = 7 janelas, depois s
    _rodar(sessao)
    ep = _json(sessao)["epocas"][0]
    assert ep["baseline_n"] == 7 and ep["baseline_insuficiente"] is True


def test_ia_sem_baseline_e_nao_avaliou_e_nao_nao_detectou(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 45, "a")])
    _rodar(sessao)
    av = _json(sessao)
    (ev,) = av["eventos"]
    assert ev["ia"]["avaliou"] is False and ev["ia"]["detectado"] is False
    assert ev["ia"]["resultado"] == "n\u00e3o avaliou (sem baseline)"
    assert av["faixas"]["ia"]["episodios_total"] == 0 and av["faixas"]["ia"]["episodios_sem_baseline"] == 1
    assert ev["mega"]["detectado"] is not None  # as outras faixas seguem avaliadas
    saida = _rodar(sessao)
    assert "nao avaliou" in saida and "sem baseline" in saida


def test_ia_avaliada_true_nas_janelas_julgadas(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 50, "a")])
    _rodar(sessao)
    por = {l["janela_mega"]: l for l in _jsonl(sessao)}
    assert por[51]["ia"]["avaliada"] is True and por[10]["ia"] is None
    (ev,) = _json(sessao)["eventos"]
    assert ev["ia"]["avaliou"] is True and "resultado" not in ev["ia"]


# ------------------------------------------------------------ I1: janelas depois do disparo nao entram na conta
def _estado_trip(trip):
    return lambda e, j: "ALERTA" if j >= trip else "NORMAL"


def test_pos_disparo_motor_parado_com_rotulo_a_nao_conta_alarme_da_ia(tmp_path):
    """Mega trava em 50; rele corta o motor (rpm 0) e o rotulo continua a. A ia alarma depois do disparo: nao conta."""
    rpm = lambda e, j: 0 if j >= 52 else 2000 + 60 * ((j % 3) - 1)
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 48, "a")], rpm=rpm, estado=_estado_trip(50))
    _rodar(sessao)
    linhas = _jsonl(sessao)
    pos = [l for l in linhas if l["janela_mega"] > 50]
    assert pos and all(l["pos_disparo"] is True for l in pos)
    assert not any(l["pos_disparo"] for l in linhas if l["janela_mega"] <= 50)
    assert any(l["ia"] and l["ia"]["disparou"] for l in pos)  # a ia alarma, mas...
    av = _json(sessao)
    assert av["epocas"][0]["disparo_mega_janela"] == 50
    assert av["faixas"]["ia"]["falsos_alarmes"] == 0 and av["faixas"]["mega"]["falsos_alarmes"] == 0
    # o episodio a fica de pe e o atraso e' medido do inicio; a janela do ALERTA conta
    (ev,) = av["eventos"]
    assert ev["mega"]["detectado"] is True and ev["mega"]["atraso"] == 1  # inicio 49, ALERTA em 50


def test_pos_disparo_ia_que_so_alarma_depois_do_disparo_nao_detecta(tmp_path):
    rpm = lambda e, j: 0 if j >= 52 else 2000 + 60 * ((j % 3) - 1)
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 48, "a")], rpm=rpm, estado=_estado_trip(50))
    _rodar(sessao)
    (ev,) = _json(sessao)["eventos"]
    assert ev["ia"]["avaliou"] is True and ev["ia"]["detectado"] is False


def test_pos_disparo_caso_r_da_sonda(tmp_path):
    """r em 60; Mega trava em 62; rele corta o motor em 63; ruido da sala continua. Os alarmes da ia de 63 em diante
    (inconsistencia com motor parado) nao sao falsos alarmes; 61 e 62 contam (a guarda nao vale para r)."""
    rpm = lambda e, j: 0 if j >= 63 else 2000 + 60 * ((j % 3) - 1)
    som = lambda e, j: 75 if j >= 61 else 60 + (j % 3)
    sessao = _sessao_manual(tmp_path, n=75, rot=[(1, 33, "n"), (1, 60, "r"), (1, 68, "x")],
                            rpm=rpm, som=som, estado=_estado_trip(62))
    _rodar(sessao)
    linhas = _jsonl(sessao)
    assert any(l["ia"]["disparou"] for l in linhas if 63 <= l["janela_mega"] <= 68)
    av = _json(sessao)
    # r mede o falso alarme honesto: a guarda nao o perdoa, nem na janela do ALERTA (62); 63+ e' pos-disparo (x)
    assert av["faixas"]["mega"]["falsos_alarmes"] == 1
    assert 1 <= av["faixas"]["ia"]["falsos_alarmes"] <= 2   # so 61 e 62; os 6 alarmes de 63 a 68 ficam fora
    # o rotulo cru continua r: a conta e' que muda, nao o que o operador marcou
    assert [l["rotulo"] for l in linhas if l["janela_mega"] == 64] == ["r"]


def test_pos_disparo_o_alerta_da_janela_do_disparo_ainda_conta_como_falso_alarme_fora_da_guarda(tmp_path):
    """Mega trava em 56 durante n (sem nenhuma tecla de falha perto): a janela 56 e' falso alarme do Mega; 57+ nao."""
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n")], estado=_estado_trip(56))
    _rodar(sessao)
    av = _json(sessao)
    assert av["faixas"]["mega"]["falsos_alarmes"] == 1  # so a janela 56


def test_pos_disparo_m_com_tecla_2s_atrasada(tmp_path):
    """Falha em 49 (som some); Mega trava em 50; a tecla m so chega depois (rotula de 52 em diante). Tudo que vem
    depois do disparo e' x: a ia nao leva falso alarme das janelas n 49-50 (guarda) nem das 51+ (pos-disparo);
    o episodio m inteiro fica depois do disparo e e' listado como excluido, sem virar 'nao detectou'."""
    som = lambda e, j: 5 if j >= 49 else 60 + (j % 3)
    rpm = lambda e, j: 0 if j >= 52 else 2000 + 60 * ((j % 3) - 1)
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 51, "m")], rpm=rpm, som=som, estado=_estado_trip(50))
    _rodar(sessao)
    av = _json(sessao)
    (ev,) = av["eventos"]
    assert ev["excluido"] is True and ev["rotulo"] == "m" and ev["janela_mega_inicio"] == 52
    # o Mega disparou com o rotulo ainda n: e' o texto do falso alarme em normal
    assert ev["resultado"] == "exclu\u00eddo: o Mega disparou com o r\u00f3tulo ainda em normal (falso alarme, ou tecla apertada tarde: aperte antes do gesto; resete o Mega)"
    assert "excluido: o Mega disparou com o rotulo ainda em normal" in _rodar(sessao)
    assert av["faixas"]["ia"]["episodios_total"] == 0   # nao vira "nao detectou"
    assert av["epocas"][0]["episodios_pos_disparo"] == ["m"]
    assert av["faixas"]["ia"]["falsos_alarmes"] == 0 and av["faixas"]["mega"]["falsos_alarmes"] == 0


def test_pos_disparo_sem_alerta_nada_muda(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 50, "a")])
    _rodar(sessao)
    linhas = _jsonl(sessao)
    assert not any(l["pos_disparo"] for l in linhas)
    assert _json(sessao)["epocas"][0]["disparo_mega_janela"] is None


def test_canal_ausente_nao_chama_tipar_e_nao_dispara(tmp_path, monkeypatch):
    """Espiao: tipar levanta se for chamado numa janela com canal ausente."""
    import metricas
    visto = []
    original = metricas.tipar

    def espiao(janela, baseline):
        visto.append(janela["janela_mega"])
        if janela["rpm"] is None:
            raise AssertionError("tipar chamado com rpm ausente")
        return original(janela, baseline)

    monkeypatch.setattr(metricas, "tipar", espiao)
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 52, "p")],
                            rpm=lambda e, j: None if 55 <= j <= 58 else 2000 + 60 * ((j % 3) - 1))
    dados = avaliar.carregar(sessao)
    linhas, _ = avaliar.avaliar_sessao(dados)
    por = {l["janela_mega"]: l for l in linhas}
    for j in (55, 56, 57, 58):
        ia = por[j]["ia"]
        assert j not in visto
        assert ia["disparou"] is False and ia["classe"] == "canal_ausente" and ia["por_que"]
        assert por[j]["classe_final"] == "canal_ausente"
    assert 54 in visto and 59 in visto  # o espiao esta mesmo ligado


def test_duas_teclas_na_mesma_janela_a_ultima_vence():
    r = avaliar.expandir_rotulos(_jan(1, 2, 3, 4, 5), [(2, "a"), (2, "p")])
    assert r == [None, None, "p", "p", "p"]


def test_tecla_n_antes_da_calibracao_nao_antecipa_o_baseline(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 20, "n"), (1, 48, "a")])
    _rodar(sessao)
    ep = _json(sessao)["epocas"][0]
    assert ep["baseline_n"] == 15 and ep["baseline_ate_janela"] == 48  # 34..48, nao 21..48


def test_baseline_para_exatamente_no_primeiro_rotulo_nao_n(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 50, "a"), (1, 55, "n")])
    _rodar(sessao)
    ep = _json(sessao)["epocas"][0]
    assert ep["baseline_n"] == 17 and ep["baseline_ate_janela"] == 50  # 34..50; o n tardio (56+) fica fora
    por = {l["janela_mega"]: l for l in _jsonl(sessao)}
    assert por[50]["ia"] is None and por[51]["ia"] is not None


def test_baseline_max_negativo_e_rejeitado(tmp_path):
    sessao = _simular(tmp_path, "nulo")
    r = subprocess.run([sys.executable, "-I", AVALIAR, sessao, "--baseline-max", "-1"], capture_output=True, text=True)
    assert r.returncode != 0 and "baseline-max" in r.stderr


# ------------------------------------------------------------ fumaca: completo seed 7
@pytest.fixture(scope="module")
def completo(tmp_path_factory):
    sessao = _simular(tmp_path_factory.mktemp("completo"), "completo")
    saida = _rodar(sessao)
    return sessao, saida


def test_uma_linha_por_janela_com_o_esquema_do_brief(completo):
    sessao, _ = completo
    with open(os.path.join(sessao, "sinais.csv")) as f:
        n = sum(1 for _ in f) - 1
    linhas = _jsonl(sessao)
    assert len(linhas) == n == 660
    for l in linhas:
        assert {"t_s", "epoca", "janela_mega", "rotulo", "limiar", "mega", "ia", "saude", "classe_final", "pos_disparo"} <= set(l)
        assert l["ia"] is None or {"avaliada", "disparou", "classe", "por_que"} <= set(l["ia"])


def test_tabela_por_evento_lista_todo_episodio_apm_com_ia_detectado(completo):
    """SMOKE TEST (simulado): cada episodio a/p/m (3 de cada, 1 por epoca) e' visto pela faixa ia."""
    sessao, _ = completo
    ev = _json(sessao)["eventos"]
    assert sorted(e["rotulo"] for e in ev) == ["a"] * 3 + ["m"] * 3 + ["p"] * 3
    for e in ev:
        assert e["ia"]["detectado"] is True, e
        assert {"limiar", "mega", "ia", "classe_final", "epoca"} <= set(e)


def test_ia_separa_anomalia_de_inconsistencia_no_simulado(completo):
    sessao, _ = completo
    for e in _json(sessao)["eventos"]:
        esperado = "anomalia" if e["rotulo"] == "a" else "inconsistencia"
        assert e["ia"]["classe"] == esperado, e


def test_s_classe_final_nunca_e_anomalia_nem_inconsistencia(completo):
    """Ruling: contexto vence modelo. ia SEM contexto marca a parada comandada; classe_final = evento_esperado."""
    sessao, _ = completo
    s = [l for l in _jsonl(sessao) if l["rotulo"] == "s"]
    assert s
    assert not [l for l in s if l["classe_final"] in ("anomalia", "inconsistencia")]
    disparou = [l for l in s if l["ia"] and l["ia"]["disparou"]]
    assert all(l["classe_final"] == "evento_esperado" for l in disparou)


def test_alarmes_em_s_sao_reportados_nao_exigidos_zero(completo):
    """A parada comandada e' fora de distribuicao: ia PODE disparar em s (so reportamos); o mega trava em s por desenho."""
    sessao, _ = completo
    a = _json(sessao)
    for faixa in ("limiar", "mega", "ia"):
        assert isinstance(a["faixas"][faixa]["alarmes_em_s"], int)
    assert a["segmentos_contexto"]


def test_ia_nula_antes_do_fim_do_baseline_e_baseline_de_15(completo):
    sessao, _ = completo
    ep = _json(sessao)["epocas"]
    assert len(ep) == 11 and all(e["baseline_n"] == 15 and not e["baseline_insuficiente"] for e in ep)
    for l in _jsonl(sessao):
        if l["janela_mega"] <= 48:
            assert l["ia"] is None


def test_resumo_ascii(completo):
    _, saida = completo
    saida.encode("ascii")
    assert "ia" in saida and "falsos" in saida.lower()


def test_exemplo_commitado_bate_com_uma_rodada_nova(tmp_path):
    import shutil
    copia = tmp_path / "ex"
    shutil.copytree(EXEMPLO, copia, ignore=shutil.ignore_patterns("detectores.jsonl", "avaliacao.json"))
    _rodar(copia)
    for nome in ("detectores.jsonl", "avaliacao.json"):
        assert (copia / nome).read_text() == open(os.path.join(EXEMPLO, nome)).read()


# ------------------------------------------------------------ fumaca: nulo
def test_nulo_ia_nao_dispara_em_janela_n(tmp_path):
    """SMOKE TEST (simulado): teto de falsos alarmes da faixa ia no cenario nulo = 0.
    --baseline-max 30 deixa as demais janelas n fora da amostra (senao a epoca toda vira baseline e ia fica nula)."""
    sessao = _simular(tmp_path, "nulo")
    _rodar(sessao, "--baseline-max", "30")
    linhas = _jsonl(sessao)
    avaliadas = [l for l in linhas if l["rotulo"] == "n" and l["ia"] is not None]
    assert len(avaliadas) > 50  # o teste nao e' vazio
    assert [l for l in avaliadas if l["ia"]["disparou"]] == []
    assert _json(sessao)["faixas"]["ia"]["falsos_alarmes"] == 0


def test_nulo_sem_teto_toda_a_epoca_e_baseline_e_ia_fica_nula(tmp_path):
    sessao = _simular(tmp_path, "nulo")
    _rodar(sessao)
    assert all(l["ia"] is None for l in _jsonl(sessao))  # tem baseline (sem avaliar as proprias janelas), nao e' "sem baseline"


def test_guarda_nao_perdoa_alarme_em_r_mas_perdoa_em_n(tmp_path):
    """Mega trava em 54, em r (r de 50 a 55, bem depois da troca n->r em 50): conta. O mesmo disparo numa janela n
    colada numa troca de rotulo continua perdoado."""
    rot_r = [(1, 33, "n"), (1, 49, "r"), (1, 58, "x")]
    sessao = _sessao_manual(tmp_path, rot=rot_r, estado=_estado_trip(51), nome="r")
    _rodar(sessao)
    assert _json(sessao)["faixas"]["mega"]["falsos_alarmes"] == 1   # janela 51 (1a ALERTA) dentro da guarda do n->r, ainda assim conta
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 49, "a")], estado=_estado_trip(49), nome="n")  # ALERTA na ultima n (49)
    _rodar(sessao)
    assert _json(sessao)["faixas"]["mega"]["falsos_alarmes"] == 0


# ------------------------------------------------------------ rodada final: contexto, baseline, falso alarme em n
def test_contexto_conta_so_janelas_antes_do_disparo(tmp_path):
    rpm = lambda e, j: 0 if j >= 63 else 2000 + 60 * ((j % 3) - 1)
    som = lambda e, j: 75 if j >= 61 else 60 + (j % 3)
    sessao = _sessao_manual(tmp_path, n=75, rot=[(1, 33, "n"), (1, 60, "r"), (1, 68, "x")], rpm=rpm, som=som, estado=_estado_trip(62))
    _rodar(sessao)
    (seg,) = _json(sessao)["segmentos_contexto"]
    assert seg["rotulo"] == "r" and seg["janela_mega_inicio"] == 61
    assert seg["janelas"] == 2 and seg["janelas_marcadas"] == 8   # 61 e 62; 63 a 68 sao pos-disparo
    assert seg["ia_avaliadas"] <= 2 and seg["ia_alarmes"] <= 2 and seg["mega_alarmes"] == 1


def test_baseline_para_na_janela_do_disparo(tmp_path):
    """Sem nenhuma tecla de falha: janelas sem rotulo depois do disparo (motor parado) nao entram no baseline."""
    sessao = _sessao_manual(tmp_path, rot=[], estado=_estado_trip(50), rpm=lambda e, j: 0 if j > 50 else 2000 + 60 * ((j % 3) - 1))
    _rodar(sessao)
    ep = _json(sessao)["epocas"][0]
    assert ep["baseline_ate_janela"] == 49 and ep["baseline_n"] == 16   # 34..49


def test_disparo_em_normal_explica_o_episodio_excluido_sem_mandar_apertar_a_tecla(tmp_path):
    """Mega dispara na janela 45, ainda n; a tecla de falha so vem depois: o texto nao pode culpar a tecla."""
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 50, "a")], estado=_estado_trip(45))
    _rodar(sessao)
    av = _json(sessao)
    (ev,) = av["eventos"]
    assert av["epocas"][0]["disparo_em_normal"] is True
    assert ev["resultado"] == "exclu\u00eddo: o Mega disparou com o r\u00f3tulo ainda em normal (falso alarme, ou tecla apertada tarde: aperte antes do gesto; resete o Mega)"
    assert "aperte a tecla" not in ev["resultado"]


def test_tecla_so_depois_do_disparo_com_falha_ja_marcada_manda_apertar_antes_do_gesto(tmp_path):
    sessao = _sessao_manual(tmp_path, rot=[(1, 33, "n"), (1, 48, "a"), (1, 54, "p")], estado=_estado_trip(50))
    _rodar(sessao)
    av = _json(sessao)
    excl = [e for e in av["eventos"] if e.get("excluido")]
    assert [e["rotulo"] for e in excl] == ["p"] and av["epocas"][0]["disparo_em_normal"] is False
    assert excl[0]["resultado"] == "exclu\u00eddo: r\u00f3tulo depois do disparo (aperte a tecla antes do gesto)"
    assert "excluido: rotulo depois do disparo (aperte a tecla antes do gesto)" in _rodar(sessao)
