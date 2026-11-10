"""Testes de metricas.py. Cada expectativa deriva das regras do plano, nao da execucao."""
import math

import pytest

import metricas as m


def J(rpm=1000.0, som_rms=30.0, som_pico=60.0, vib=10.0):
    return {"rpm": rpm, "som_rms": som_rms, "som_pico": som_pico, "vib": vib}


# ---------- features ----------
def test_crista_som_rms_zero_e_none():
    # regra: crista = pico/rms, None se rms <= 0
    assert m.features(J(som_rms=0.0, som_pico=5.0))["crista"] is None
    assert m.features(J(som_rms=-1.0))["crista"] is None


def test_crista_valor():
    # 60/30 = 2
    assert m.features(J(som_rms=30.0, som_pico=60.0))["crista"] == pytest.approx(2.0)


def test_vib_por_rev_rpm_zero_e_none():
    # regra: None se rpm <= 60 (um degrau de contagem; PULSOS_POR_VOLTA = 1)
    assert m.features(J(rpm=0.0))["vib_por_rev"] is None
    assert m.features(J(rpm=60.0))["vib_por_rev"] is None  # igual ao degrau: ainda None
    # rpm 120 -> 2 rev/s ; vib 10 / 2 = 5
    assert m.features(J(rpm=120.0, vib=10.0))["vib_por_rev"] == pytest.approx(5.0)


def test_features_nao_altera_entrada_e_aceita_none():
    j = J(rpm=None)
    f = m.features(j)
    assert "crista" not in j
    assert f["vib_por_rev"] is None


def test_delta_rpm_sequencia():
    # delta = rpm[i] - rpm[i-1]; primeira janela e None; None em qualquer ponta -> None
    s = m.features_serie([J(rpm=1000), J(rpm=1060), J(rpm=1000), J(rpm=None), J(rpm=900)])
    assert [f["delta_rpm"] for f in s] == [None, 60, -60, None, None]


# ---------- saude ----------
def serie(canal, valores):
    # os outros canais variam a cada janela (+k), para so `canal` poder ficar travado
    out = []
    for k, v in enumerate(valores):
        j = {c: x + k for c, x in J().items()}
        j[canal] = v
        out.append(j)
    return out


def test_canal_ausente_tres_none():
    # 3 None consecutivos terminando em i=2 -> ausente
    assert m.saude(serie("vib", [None, None, None]), 2, True)["canal_ausente"] == ["vib"]


def test_canal_ausente_dois_none_nao():
    # so 2 None terminando em i=2 (janela 0 tem valor)
    assert m.saude(serie("vib", [5.0, None, None]), 2, True)["canal_ausente"] == []
    # i=1 com 2 None mas sem 3 janelas disponiveis
    assert m.saude(serie("vib", [None, None, 5.0]), 1, True)["canal_ausente"] == []


def test_valor_travado_cinco_iguais_girando():
    # 5 valores identicos terminando em i=4 e motor girando -> travado
    s = serie("som_rms", [7.0] * 5)
    assert m.saude(s, 4, True)["valor_travado"] == ["som_rms"]


def test_valor_travado_parado_nao():
    # mesmos 5 valores, motor parado: regra so avalia com motor girando
    assert m.saude(serie("som_rms", [7.0] * 5), 4, False)["valor_travado"] == []


def test_valor_travado_quatro_iguais_nao():
    assert m.saude(serie("som_rms", [1.0, 7.0, 7.0, 7.0, 7.0]), 4, True)["valor_travado"] == []


def test_fora_da_faixa_fisica():
    # rpm 7000 > 6000
    assert m.saude(serie("rpm", [7000.0]), 0, True)["fora_da_faixa_fisica"] == ["rpm"]
    # limites inclusivos: 6000 ok, -1 fora
    assert m.saude(serie("rpm", [6000.0]), 0, True)["fora_da_faixa_fisica"] == []
    assert m.saude(serie("vib", [-1.0]), 0, True)["fora_da_faixa_fisica"] == ["vib"]
    assert m.saude(serie("som_pico", [1024.0]), 0, True)["fora_da_faixa_fisica"] == ["som_pico"]
    assert m.saude(serie("som_rms", [513.0]), 0, True)["fora_da_faixa_fisica"] == ["som_rms"]


# ---------- Baseline ----------
def normais():
    # grade 3x3 repetida: rpm {800,1000,1200} x vib {6,10,14}, som = 10 + 2*vib exato (sem ruido)
    out = []
    for r in (800.0, 1000.0, 1200.0):
        for v in (6.0, 10.0, 14.0):
            out.append(J(rpm=r, vib=v, som_rms=10 + 2 * v, som_pico=20 + 4 * v))
    return out


def test_baseline_medias_e_sd():
    b = m.Baseline(normais())
    # medias da grade: rpm 1000, vib 10, som 10+2*10 = 30
    assert b.media["rpm"] == pytest.approx(1000.0)
    assert b.media["vib"] == pytest.approx(10.0)
    assert b.media["som_rms"] == pytest.approx(30.0)
    # rpm: desvios +-200 em 6 de 9 pontos, ddof=1: sqrt(6*40000/8) = sqrt(30000)
    assert b.sd["rpm"] == pytest.approx(math.sqrt(30000.0))
    # vib: desvios +-4 em 6 de 9: sqrt(6*16/8) = sqrt(12)
    assert b.sd["vib"] == pytest.approx(math.sqrt(12.0))


def test_baseline_regressao_exata():
    b = m.Baseline(normais())
    # som_rms = 10 + 2*vib + 0*rpm
    assert b.coef_som == pytest.approx([10.0, 2.0, 0.0], abs=1e-6)  # [a, b_vib, c_rpm]
    # vib = a + b*som => vib = -5 + 0.5*som
    assert b.coef_vib == pytest.approx([-5.0, 0.5], abs=1e-6)


def test_baseline_residuo_ponto_na_reta_e_zero():
    b = m.Baseline(normais())
    r = b.residuos(J(rpm=950, vib=9.0, som_rms=28.0))  # 10 + 2*9 = 28
    assert r["som_rms"] == pytest.approx(0.0, abs=1e-6)
    assert r["vib"] == pytest.approx(0.0, abs=1e-6)


def test_baseline_residuo_em_sigma_com_piso():
    b = m.Baseline(normais())
    # residuos de treino sao 0 -> sd piso do som = 3.0. Ponto 9 abaixo da reta = -3 sigma
    r = b.residuos(J(rpm=950, vib=9.0, som_rms=28.0 - 9.0))
    assert r["som_rms"] == pytest.approx(-3.0, abs=1e-6)


def test_baseline_sd_com_piso():
    b = m.Baseline([J(rpm=1000, vib=10, som_rms=30)] * 6 + [J(rpm=1000, vib=10.0001, som_rms=30)])
    # variacao ~0: sd sobe aos pisos (rpm 60, som 3, vib 2)
    assert b.sd["rpm"] == 60.0
    assert b.sd["som_rms"] == 3.0
    assert b.sd["vib"] == 2.0


# ---------- tipar ----------
SD_RPM = math.sqrt(30000.0)
SD_VIB = math.sqrt(12.0)
# media som 30; sd do som = 2*sqrt(12); som - 1sd = 30 - 6.93 = 23.07


@pytest.fixture
def base():
    return m.Baseline(normais())


def test_tipar_a_normal(base):
    # z todos 0, residuos 0
    t = m.tipar(J(rpm=1000, vib=10, som_rms=30), base)
    assert t["classe"] == "normal"
    assert set(t) >= {"classe", "por_que", "z", "residuos"}


def test_tipar_b_anomalia_rpm_e_vib_fora_som_consistente(base):
    # rpm z = -5 (133.97 >= 60, nao dispara regra fisica), vib z = +4, som = 10 + 2*vib (na reta)
    rpm = 1000 - 5 * SD_RPM
    vib = 10 + 4 * SD_VIB
    t = m.tipar(J(rpm=rpm, vib=vib, som_rms=10 + 2 * vib), base)
    assert t["classe"] == "anomalia"
    assert t["z"]["rpm"] == pytest.approx(-5.0)
    assert t["z"]["vib"] == pytest.approx(4.0)
    assert "rpm" in t["por_que"] and "vib" in t["por_que"]  # nomeia os canais


def test_tipar_c_inconsistencia_som_6_sigma_abaixo_da_reta(base):
    # rpm e vib no centro (z=0); reta preve som 30; sd do residuo = piso 3.0; 6 sigma = 18 abaixo -> 12
    # rpm 1000 >= 60 e nao dispara regra fisica
    t = m.tipar(J(rpm=1000, vib=10, som_rms=30 - 18), base)
    assert t["classe"] == "inconsistencia"
    assert t["residuos"]["som_rms"] == pytest.approx(-6.0, abs=1e-6)
    assert "som nao bate" in t["por_que"]
    assert "som_rms" in t["por_que"]


def test_tipar_d_rpm_zero_com_som_de_motor_regra_fisica(base):
    # rpm 0 < 60 e som 30 > 30 - 6.93: som diz que gira -> inconsistencia (antes da regra de OOD)
    t = m.tipar(J(rpm=0.0, vib=10, som_rms=30), base)
    assert t["classe"] == "inconsistencia"
    assert "rpm zero com som de motor" in t["por_que"]


def test_tipar_e_rpm_zero_com_som_perto_de_zero_nao_e_regra_fisica(base):
    # som 0 < 23.07: motor comandado off. Regra fisica 1 nao vale; vib 10 nao passa de 10+3*3.46=20.4.
    # rpm z = (0-1000)/173.2 = -5.77 -> OOD -> anomalia (parada so e esperada se o contexto/rotulo disser)
    t = m.tipar(J(rpm=0.0, vib=10, som_rms=0.0), base)
    assert t["classe"] == "anomalia"
    assert "rpm zero com som" not in t["por_que"]
    assert "rpm" in t["por_que"]


def test_tipar_vibracao_sem_rotacao(base):
    # rpm 0, som 0 (regra 1 nao), vib 25 > 10 + 3*3.464 = 20.39 -> inconsistencia pela regra fisica 2
    t = m.tipar(J(rpm=0.0, vib=25.0, som_rms=0.0), base)
    assert t["classe"] == "inconsistencia"
    assert "vibracao sem rotacao" in t["por_que"]


def test_tipar_por_que_ascii(base):
    for j in (J(rpm=0.0), J(rpm=0.0, som_rms=0.0), J(som_rms=12.0), J()):
        assert m.tipar(j, base)["por_que"].isascii()


# ---------- lanes ----------
def test_lane_limiar():
    assert m.lane_limiar(J(rpm=299)) is True    # rpm < 300
    assert m.lane_limiar(J(rpm=300)) is False   # estrito
    assert m.lane_limiar(J(som_rms=201)) is True
    assert m.lane_limiar(J(som_rms=200)) is False
    assert m.lane_limiar(J(vib=51)) is True
    assert m.lane_limiar(J(vib=50)) is False


def test_lane_mega():
    assert m.lane_mega({"estado_mega": "ALERTA"}) is True
    assert m.lane_mega({"estado_mega": "NORMAL"}) is False
    assert m.lane_mega({}) is False


def test_lane_ia(base):
    r = m.lane_ia(J(rpm=0.0, vib=10, som_rms=30), base)
    assert r["disparou"] is True and r["classe"] == "inconsistencia"
    r = m.lane_ia(J(), base)
    assert r["disparou"] is False and r["classe"] == "normal"


# ---------- avaliar ----------
def alarmes_em(n, idx):
    return [i in idx for i in range(n)]


def test_avaliar_atraso_e_falsos_alarmes():
    # rotulos: n 0-7, a 8-13, x 14-15, n 16-19. Fronteiras (mudanca de rotulo) em k=8, 14, 16.
    # guarda=2 exclui [k-2, k+2]: 6-10, 12-16, 14-18.
    rot = ["n"] * 8 + ["a"] * 6 + ["x"] * 2 + ["n"] * 4
    alm = alarmes_em(20, {3, 7, 10, 15, 17, 19})
    r = m.avaliar([{}] * 20, rot, alm)
    # episodio a: inicio 8, primeiro alarme em 10 -> atraso 2
    assert r["episodios"] == [{"rotulo": "a", "inicio": 8, "detectado": True, "atraso": 2}]
    # falsos: 3 (n, fora de guarda) e 19 (n, fora de guarda). 7 e 17 em guarda; 15 e' x.
    assert r["falsos_alarmes"] == 2
    assert r["alarmes_em_s"] == 0


def test_avaliar_nao_detectado():
    rot = ["n"] * 5 + ["p"] * 5
    r = m.avaliar([{}] * 10, rot, [False] * 10)
    assert r["episodios"] == [{"rotulo": "p", "inicio": 5, "detectado": False, "atraso": None}]


def test_avaliar_alarmes_em_s():
    # s 5-14; fronteiras k=5 (guarda 3-7) e k=15 (guarda 13-17)
    rot = ["n"] * 5 + ["s"] * 10 + ["n"] * 5
    alm = alarmes_em(20, {5, 9, 11, 14})
    r = m.avaliar([{}] * 20, rot, alm)
    # 5 e 14 em guarda -> ignorados; 9 e 11 contam
    assert r["alarmes_em_s"] == 2
    assert r["falsos_alarmes"] == 0
    assert r["episodios"] == []  # s e' evento esperado, nao e' episodio a detectar


def test_avaliar_r_conta_como_falso_alarme():
    rot = ["n"] * 5 + ["r"] * 10 + ["n"] * 5
    r = m.avaliar([{}] * 20, rot, alarmes_em(20, {9}))
    assert r["falsos_alarmes"] == 1


def test_avaliar_janelas_sem_rotulo_ignoradas():
    rot = [None] * 10
    r = m.avaliar([{}] * 10, rot, [True] * 10)
    assert r["falsos_alarmes"] == 0 and r["alarmes_em_s"] == 0 and r["episodios"] == []


def test_avaliar_guarda_bordas_exatas():
    # troca de rotulo em k=10 (n -> r nao importa: ambos contam falsos). Guarda 2 => [8, 12] ignoradas.
    rot = ["n"] * 10 + ["s"] * 10  # s: alarmes_em_s usa a mesma guarda
    for idx, esperado in ((12, 0), (13, 1), (8, 0), (7, 1)):
        r = m.avaliar([{}] * 20, rot, alarmes_em(20, {idx}))
        assert r["falsos_alarmes"] + r["alarmes_em_s"] == esperado, idx


# ---------- contrato de tipar / Baseline ----------
def test_tipar_none_levanta(base):
    for c in ("rpm", "som_rms", "vib"):
        with pytest.raises(ValueError, match="canal invalido: " + c):
            m.tipar(J(**{c: None}), base)


def test_tipar_nan_levanta(base):
    for c in ("rpm", "som_rms", "vib"):
        with pytest.raises(ValueError, match="canal invalido: " + c):
            m.tipar(J(**{c: float("nan")}), base)
    with pytest.raises(ValueError):
        m.lane_ia(J(vib=float("nan")), base)


def test_baseline_sem_som_pico():
    js = [{k: v for k, v in j.items() if k != "som_pico"} for j in normais()]
    m.Baseline(js)  # nao levanta


def test_baseline_vazio_ou_none_levanta():
    with pytest.raises(ValueError):
        m.Baseline([])
    with pytest.raises(ValueError, match="canal invalido: vib"):
        m.Baseline(normais() + [J(vib=None)])


def test_baseline_ruidoso_sd_vem_dos_dados():
    import numpy as np
    rng = np.random.default_rng(7)
    js = []
    for _ in range(400):
        v = 10 + 5 * rng.standard_normal()
        js.append(J(rpm=1000 + 100 * rng.standard_normal(), vib=v, som_rms=10 + 2 * v + 5 * rng.standard_normal()))
    b = m.Baseline(js)
    # ruido do som 5 > piso 3: o sd do residuo vem dos dados (~5), nao do piso
    assert 4.0 < b.sd_res_som < 6.0
    # ponto no centro (preditores z~0) com som 10 sigma_dados acima da reta => residuo ~ +10 > 3 => inconsistencia
    pred = b.coef_som[0] + b.coef_som[1] * 10 + b.coef_som[2] * 1000
    t = m.tipar(J(rpm=1000, vib=10, som_rms=pred + 10 * b.sd_res_som), b)
    assert t["classe"] == "inconsistencia"
    assert t["residuos"]["som_rms"] == pytest.approx(10.0)
    # e o mesmo ponto sobre a reta e normal
    assert m.tipar(J(rpm=1000, vib=10, som_rms=pred), b)["classe"] == "normal"
