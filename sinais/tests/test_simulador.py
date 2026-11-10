"""Testes do simulador. Expectativas vem da regra do Mega (.ino), nao da saida do codigo."""
import math

import simulador
from simulador import MegaEmulado


def _calibrar(mega, rpm=2000.0, som=60.0, vib=5.0):
    """3 AQUECENDO + 30 CALIBRANDO com valores constantes: desvio 0 -> pisos 60 / 3 / 2."""
    estados = [mega.passo((rpm, som, vib))[1] for _ in range(33)]
    return estados


def test_aquece_calibra_contagens():
    mega = MegaEmulado()
    estados = _calibrar(mega)
    assert estados == ["AQUECENDO"] * 3 + ["CALIBRANDO"] * 30
    assert mega.passo((2000.0, 60.0, 5.0)) == (0.0, "NORMAL")


def test_aquecimento_nao_entra_na_calibracao():
    mega = MegaEmulado()
    for _ in range(3):
        mega.passo((0.0, 0.0, 0.0))  # descartadas
    for _ in range(30):
        mega.passo((2000.0, 60.0, 5.0))
    assert not mega.suspeita
    assert mega.media[0] == 2000.0


def test_limiar_estrito_score_igual_a_3_nao_conta():
    mega = MegaEmulado()
    _calibrar(mega)
    for _ in range(5):
        score, estado = mega.passo((2000.0, 69.0, 5.0))  # z = 9/3 = 3.0 exato
        assert score == 3.0 and estado == "NORMAL"


def test_uma_janela_acima_nao_dispara_duas_seguidas_disparam():
    mega = MegaEmulado()
    _calibrar(mega)
    assert mega.passo((2000.0, 69.1, 5.0))[1] == "NORMAL"
    assert mega.passo((2000.0, 69.1, 5.0))[1] == "ALERTA"


def test_janela_calma_zera_a_sequencia():
    mega = MegaEmulado()
    _calibrar(mega)
    estados = [mega.passo((2000.0, s, 5.0))[1] for s in (69.1, 60.0, 69.1, 60.0, 69.1)]
    assert estados == ["NORMAL"] * 5


def test_alerta_travado_ate_o_fim_da_epoca():
    mega = MegaEmulado()
    _calibrar(mega)
    mega.passo((2000.0, 70.0, 5.0))
    assert mega.passo((2000.0, 70.0, 5.0))[1] == "ALERTA"
    assert any("ALERTA TRAVADO" in e for e in mega.eventos)
    for _ in range(10):
        score, estado = mega.passo((2000.0, 60.0, 5.0))  # calmo
        assert estado == "ALERTA" and score == 0.0
        assert mega.eventos == []  # o disparo e narrado uma unica vez


def test_piso_do_rpm_150_rpm_e_z_2_5():
    mega = MegaEmulado()
    _calibrar(mega)
    score, estado = mega.passo((2150.0, 60.0, 5.0))  # piso 60 -> z = 2.5
    assert score == 2.5
    assert mega.passo((2150.0, 60.0, 5.0))[1] == "NORMAL"


def test_desvio_calibrado_maior_que_o_piso_prevalece():
    mega = MegaEmulado()
    for _ in range(3):
        mega.passo((2000.0, 60.0, 5.0))
    for i in range(30):  # som alterna 50/70: desvio amostral ~10,2 > piso 3
        mega.passo((2000.0, 50.0 if i % 2 else 70.0, 5.0))
    assert mega.desvio[1] > 10.0
    assert mega.passo((2000.0, 80.0, 5.0))[0] < 3.0  # z ~ 2 com o desvio real, seria 6,7 com o piso


def test_suspeita_com_rpm_medio_abaixo_de_60_nunca_arma():
    mega = MegaEmulado()
    estados = [mega.passo((0.0, 60.0, 5.0))[1] for _ in range(33)]
    assert estados[-1] == "CALIBRANDO" and mega.suspeita
    assert any("SUSPEITA" in e for e in mega.eventos)
    for _ in range(5):
        assert mega.passo((2000.0, 200.0, 50.0)) == (0.0, "SUSPEITA")


def test_rpm_medio_exatamente_60_nao_e_suspeita():
    mega = MegaEmulado()
    for _ in range(33):
        mega.passo((60.0, 60.0, 5.0))
    assert not mega.suspeita


def test_mesma_semente_mesmo_resultado():
    assert simulador.simular("completo", 7) == simulador.simular("completo", 7)
    assert simulador.simular("completo", 7) != simulador.simular("completo", 8)


def test_cenario_desconhecido():
    try:
        simulador.simular("xyz", 1)
    except ValueError:
        return
    raise AssertionError("esperava ValueError")


def _por_epoca(sim):
    epocas = {}
    for s in sim["sinais"]:
        epocas.setdefault(s["epoca"], []).append(s)
    return epocas


def test_nulo_nunca_dispara_e_so_tem_rotulo_n():
    for seed in range(1, 21):
        sim = simulador.simular("nulo", seed)
        assert all(s["estado_mega"] != "ALERTA" for s in sim["sinais"]), seed
        assert {r["rotulo"] for r in sim["rotulos"]} == {"n"}
        assert max(s["score_mega"] for s in sim["sinais"]) <= 3.0, seed


def test_epocas_comecam_com_33_janelas_de_aquecimento_e_calibracao():
    sim = simulador.simular("completo", 7)
    for janelas in _por_epoca(sim).values():
        assert [j["janela_mega"] for j in janelas] == list(range(1, len(janelas) + 1))
        estados = [j["estado_mega"] for j in janelas[:33]]
        assert estados == ["AQUECENDO"] * 3 + ["CALIBRANDO"] * 30
        assert len(janelas) >= 33 + 15  # baseline n de pelo menos 15 janelas


def test_completo_episodios_por_rotulo():
    sim = simulador.simular("completo", 7)
    gestos = {}
    for r in sim["rotulos"]:
        if r["rotulo"] not in ("n", "x"):
            gestos.setdefault(r["rotulo"], []).append(r["epoca"])
    assert len(gestos["a"]) >= 3 and len(gestos["p"]) >= 3 and len(gestos["m"]) >= 3
    assert len(gestos["s"]) == 1 and len(gestos["r"]) == 1
    assert {r["rotulo"] for r in sim["rotulos"]} == {"n", "a", "p", "m", "s", "r", "x"}


def test_cada_epoca_tem_n_gesto_x_nessa_ordem_com_baseline_de_15_janelas():
    sim = simulador.simular("completo", 7)
    for epoca, janelas in _por_epoca(sim).items():
        teclas = [r for r in sim["rotulos"] if r["epoca"] == epoca]
        assert [t["rotulo"] for t in teclas][0] == "n" and [t["rotulo"] for t in teclas][-1] == "x"
        assert len(teclas) == 3
        assert teclas[1]["janela_mega"] - teclas[0]["janela_mega"] >= 15


def test_latch_emulado_alerta_do_disparo_ate_o_fim_da_epoca():
    sim = simulador.simular("completo", 7)
    for epoca, janelas in _por_epoca(sim).items():
        teclas = [r for r in sim["rotulos"] if r["epoca"] == epoca]
        gesto = teclas[1]
        estados = [j["estado_mega"] for j in janelas]
        primeiro = estados.index("ALERTA")
        assert all(e == "ALERTA" for e in estados[primeiro:]), epoca
        assert all(e != "ALERTA" for e in estados[:primeiro])
        # falha forte desde a 1a janela do gesto: 2 janelas seguidas > 3,0 -> disparo na 2a
        assert janelas[primeiro]["janela_mega"] == gesto["janela_mega"] + 2, epoca
        # x so depois do disparo
        assert teclas[2]["janela_mega"] >= janelas[primeiro]["janela_mega"]
        # o disparo e narrado uma unica vez por epoca
        narr = [e for e in sim["eventos"] if e["epoca"] == epoca and "ALERTA TRAVADO" in e["texto"]]
        assert len(narr) == 1


def test_canais_finitos_e_nao_negativos():
    for cen in ("completo", "nulo"):
        for s in simulador.simular(cen, 3)["sinais"]:
            for c in ("rpm", "som_rms", "som_pico", "vib", "score_mega"):
                assert s[c] is not None and math.isfinite(s[c]) and s[c] >= 0, (c, s)


def test_fisica_dos_gestos():
    sim = simulador.simular("completo", 7)
    for epoca, janelas in _por_epoca(sim).items():
        teclas = [r for r in sim["rotulos"] if r["epoca"] == epoca]
        g, k = teclas[1]["rotulo"], teclas[1]["janela_mega"]
        base = [j for j in janelas[3:33]]
        rpm_n = sum(j["rpm"] for j in base) / 30
        som_n = sum(j["som_rms"] for j in base) / 30
        vib_n = sum(j["vib"] for j in base) / 30
        f = janelas[k]  # janela k+1 (1-based) e a primeira do gesto
        if g == "a":
            assert f["rpm"] < rpm_n - 200 and f["vib"] > 1.5 * vib_n and f["som_rms"] > som_n + 10
        elif g == "p":
            assert f["rpm"] == 0 and abs(f["som_rms"] - som_n) < 6 and abs(f["vib"] - vib_n) < 3
        elif g == "m":
            assert f["som_rms"] < 6 and abs(f["rpm"] - rpm_n) < 150 and abs(f["vib"] - vib_n) < 3
        elif g == "s":
            assert f["rpm"] == 0 and f["som_rms"] < 6 and f["vib"] == 0
        elif g == "r":
            assert f["som_rms"] > som_n + 8 and abs(f["rpm"] - rpm_n) < 150
