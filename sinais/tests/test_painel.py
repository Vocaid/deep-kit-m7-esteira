"""O painel e' um HTML estatico sem build: aqui so' garantimos que ele le os campos que avaliar.py grava
(a verificacao de comportamento e' feita no navegador, ver final-fix-report.md)."""
import os

DIR_SINAIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(DIR_SINAIS, "painel", "index.html"), encoding="utf-8").read()


def test_painel_le_avaliada_pos_disparo_e_avaliou():
    for trecho in ("ia.avaliada === false", "d.pos_disparo", "i.avaliou === false"):
        assert trecho in HTML


def test_painel_textos_combinados():
    for texto in ("sem baseline", "não avaliou (sem baseline)", "pós-disparo (relé B cortou o motor)", "(falso alarme)"):
        assert texto in HTML


def test_painel_valor_travado_so_para_som():
    assert 'filter(c => c.startsWith("som"))' in HTML
    assert 'valor_travado.join' not in HTML


def test_painel_carta_pos_disparo_e_contexto_antes_do_disparo():
    assert "motor parado pelo relé B (janela pós-disparo)" in HTML and "antes do disparo" in HTML


def test_painel_mostra_episodio_excluido_pos_disparo():
    assert "e.excluido" in HTML and "e.resultado" in HTML
