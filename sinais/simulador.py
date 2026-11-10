"""Simulador da bancada M7: gera janelas de 1 s a partir de um modelo fisico de brinquedo, com semente.

Modelo: rpm ~ 2000; vib ~ 5; som_rms = 40 + 0,01*rpm + 0,5*vib + ruido.
Falhas (ver FALHAS): a atrito, p palheta solta, m microfone tampado, s parada pelo app, r ruido da sala.

Cada epoca e um "reset" da placa: 3 AQUECENDO + 30 CALIBRANDO, bloco normal `n`, um gesto, o disparo
e `x` ate o fim da epoca. Texto de saida em ASCII.
"""
import math
import random

JANELAS_AQUECE = 3
JANELAS_CALIB = 30
JANELAS_PARA_ALERTA = 2
LIMIAR_Z = 3.0
# Pisos do firmware (PISO[]): rpm 60/PULSOS_POR_VOLTA (=60), som 3, vib 2.
PISOS = (60.0, 3.0, 2.0)

N_BASE = 15      # janelas normais (n) depois da calibracao, antes do gesto
N_FALHA = 6      # janelas com a falha ativa antes de apertar x
N_POS = 6        # janelas depois do disparo (x): motor cortado pelo rele
PAUSA_RESET_S = 5.0

SIGMA_RPM = 40.0
SIGMA_SOM = 1.0
SIGMA_VIB = 1.0
RPM_BASE = 2000.0
VIB_BASE = 5.0

ROTULOS_COMPLETO = ("a", "p", "m", "a", "p", "m", "a", "p", "m", "s", "r")
ROTULOS_NULO = ("n", "n")

FALHAS = {"a", "p", "m", "s", "r"}

TEXTO_ALERTA = ("ALERTA TRAVADO: rele (KY-019) abriu e cortou o motor; "
                "so o reset da placa rearma (sem rearme automatico)")


def ruido(rng, sigma):
    """Ruido gaussiano de desvio `sigma`, limitado a 2 sigma. Ruido limitado a 2 sigma para que o cenario
    nulo seja um teste de fumaca significativo (nenhum z > 3 espurio). Deterministico por semente."""
    return max(-2.0 * sigma, min(2.0 * sigma, rng.gauss(0.0, sigma)))


# ---------------------------------------------------------------------------------------------------
# Emulacao da regra do Mega (arduino-mega-esteira-ky.ino): so para o simulador produzir uma coluna
# `estado_mega` realista. A faixa real usa a coluna GRAVADA, nunca esta emulacao.
# ---------------------------------------------------------------------------------------------------
class MegaEmulado:
    """3 AQUECENDO (descartadas), 30 CALIBRANDO (Welford, desvio amostral, com pisos), depois
    score = max|z| sobre (rpm, som_rms, vib); ALERTA apos 2 janelas seguidas com score > 3,0 (estrito),
    travado ate o fim da epoca; SUSPEITA se a media de rpm na calibracao for < 60 (nunca arma)."""

    def __init__(self):
        self.janela = 0
        self.n = 0
        self.media = [0.0, 0.0, 0.0]
        self.m2 = [0.0, 0.0, 0.0]
        self.desvio = list(PISOS)
        self.streak = 0
        self.travado = False
        self.suspeita = False
        self.eventos = []  # textos emitidos nesta janela (antes da linha), como as linhas # do firmware

    def passo(self, x):
        """x = (rpm, som_rms, vib). Devolve (score, estado) da janela; self.eventos traz as narracoes."""
        self.eventos = []
        self.janela += 1
        score = 0.0
        if self.janela <= JANELAS_AQUECE:
            return score, "AQUECENDO"
        if self.janela <= JANELAS_AQUECE + JANELAS_CALIB:
            self.n += 1
            for i in range(3):
                delta = x[i] - self.media[i]
                self.media[i] += delta / self.n
                self.m2[i] += delta * (x[i] - self.media[i])
            if self.n == JANELAS_CALIB:
                partes = []
                for i in range(3):
                    sd = math.sqrt(self.m2[i] / (self.n - 1))
                    self.desvio[i] = sd if sd > PISOS[i] else PISOS[i]
                    partes.append("c%d media=%.1f desvio=%.2f" % (i, self.media[i], self.desvio[i]))
                self.eventos.append("calibrado: " + " ".join(partes))
                if self.media[0] < PISOS[0]:
                    self.suspeita = True
                    self.eventos.append("SUSPEITA: motor cortado -- de reset com o motor girando")
            return score, "CALIBRANDO"
        if self.suspeita:
            return score, "SUSPEITA"
        score = max(abs((x[i] - self.media[i]) / max(self.desvio[i], 1e-3)) for i in range(3))
        self.streak = self.streak + 1 if score > LIMIAR_Z else 0
        alerta = self.travado or self.streak >= JANELAS_PARA_ALERTA
        if alerta and not self.travado:
            self.travado = True
            self.eventos.append(TEXTO_ALERTA)
        return score, "ALERTA" if alerta else "NORMAL"


# ---------------------------------------------------------------------------------------------------
# Modelo fisico
# ---------------------------------------------------------------------------------------------------
def _janela_normal(rng):
    rpm = round((RPM_BASE + ruido(rng, SIGMA_RPM)) / 60.0) * 60.0  # o Mega conta pulsos: multiplos de 60
    vib = max(0.0, float(round(VIB_BASE + ruido(rng, SIGMA_VIB))))
    som = 40.0 + 0.01 * rpm + 0.5 * vib + ruido(rng, SIGMA_SOM)
    return rpm, som, vib


def _janela_parada(rng):
    """Motor cortado ou parado pelo app: rpm 0, som ~2, vib ~0."""
    return 0.0, max(0.0, 2.0 + ruido(rng, 0.5)), 0.0


def _janela_falha(rng, rotulo):
    rpm, som, vib = _janela_normal(rng)
    if rotulo == "a":      # atrito: todos os canais concordam
        rpm = rpm - 300.0
        vib = vib * 3.0
        som = 40.0 + 0.01 * rpm + 0.5 * vib + 20.0 + ruido(rng, SIGMA_SOM)
    elif rotulo == "p":    # palheta solta: rpm le 0, som e vib seguem em regime
        rpm = 0.0
    elif rotulo == "m":    # microfone tampado: som ~2, o resto normal
        som = max(0.0, 2.0 + ruido(rng, 0.5))
    elif rotulo == "s":    # parada comandada
        return _janela_parada(rng)
    elif rotulo == "r":    # ruido da sala: so o som
        som = som + 15.0
    return rpm, som, vib


def _linha(rng, rpm, som, vib):
    pico = max(0, round(som * 1.5 + ruido(rng, 2.0)))
    return {"rpm": rpm, "som_rms": round(som, 1), "som_pico": float(pico), "vib": vib}


def gerar_epoca(rotulo, rng):
    """Uma epoca: lista de janelas (dicts rpm, som_rms, som_pico, vib) e as teclas
    [(indice_da_janela_vista_antes, tecla)]. Indice 1-based da janela do Mega; a tecla vale
    para as janelas seguintes. `n` = epoca so normal (cenario nulo)."""
    janelas, teclas = [], []
    for _ in range(JANELAS_AQUECE + JANELAS_CALIB):
        janelas.append(_linha(rng, *_janela_normal(rng)))
    teclas.append((len(janelas), "n"))
    if rotulo == "n":
        for _ in range(60):
            janelas.append(_linha(rng, *_janela_normal(rng)))
        return janelas, teclas
    for _ in range(N_BASE):
        janelas.append(_linha(rng, *_janela_normal(rng)))
    teclas.append((len(janelas), rotulo))
    for _ in range(N_FALHA):
        janelas.append(_linha(rng, *_janela_falha(rng, rotulo)))
    teclas.append((len(janelas), "x"))
    for _ in range(N_POS):
        janelas.append(_linha(rng, *_janela_parada(rng)))  # o rele cortou o motor
    return janelas, teclas


def simular(cenario="completo", seed=0):
    """Devolve {"sinais": [...], "eventos": [...], "rotulos": [...]} (listas de dicts). Deterministico."""
    if cenario == "completo":
        sequencia = ROTULOS_COMPLETO
    elif cenario == "nulo":
        sequencia = ROTULOS_NULO
    else:
        raise ValueError("cenario desconhecido: %r" % (cenario,))
    sinais, eventos, rotulos = [], [], []
    t = 0.0
    for k, rotulo in enumerate(sequencia):
        epoca = k + 1
        rng = random.Random(seed * 1000 + epoca)
        janelas, teclas = gerar_epoca(rotulo, rng)
        mega = MegaEmulado()
        teclas_por_janela = {}
        for j, tecla in teclas:
            teclas_por_janela.setdefault(j, []).append(tecla)
        t += PAUSA_RESET_S if k else 0.0
        for i, w in enumerate(janelas, start=1):
            t += 1.0
            score, estado = mega.passo((w["rpm"], w["som_rms"], w["vib"]))
            for texto in mega.eventos:
                eventos.append({"t_s": t, "epoca": epoca, "texto": texto})
            sinais.append({"t_s": t, "epoca": epoca, "janela_mega": i, "rpm": w["rpm"],
                           "som_rms": w["som_rms"], "som_pico": w["som_pico"], "vib": w["vib"],
                           "score_mega": round(score, 1), "estado_mega": estado})
            for tecla in teclas_por_janela.get(i, []):
                rotulos.append({"t_s": t + 0.5, "epoca": epoca, "janela_mega": i, "rotulo": tecla})
    return {"sinais": sinais, "eventos": eventos, "rotulos": rotulos}
