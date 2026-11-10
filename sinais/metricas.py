"""Metricas da bancada M7: features por janela de 1 s, saude dos canais, tipagem
anomalia x inconsistencia, tres faixas de deteccao e avaliacao contra rotulos.
Unica implementacao; so numpy. Textos de saida em ASCII PT-BR.

Os pisos espelham PISO[] do firmware (arduino-mega-esteira-ky.ino):
rpm = 60/PULSOS_POR_VOLTA (um degrau de contagem), som 3.0, vib 2.0.
"""
import numpy as np

PULSOS_POR_VOLTA = 1
DEGRAU_RPM = 60.0 / PULSOS_POR_VOLTA
PISO = {"rpm": DEGRAU_RPM, "som_rms": 3.0, "som_pico": 3.0, "vib": 2.0}
CANAIS = ("rpm", "som_rms", "som_pico", "vib")
FAIXA_FISICA = {"rpm": (0, 6000), "som_rms": (0, 512), "som_pico": (0, 1023), "vib": (0, 500)}
LIMIAR_Z = 3.0
BASE_CANAIS = ("rpm", "som_rms", "vib")  # som_pico nao entra no baseline

# lane_limiar: limites escolhidos a mao (sem dados), a faixa mais simples da escada.
LIMIAR_RPM_MIN = 300
LIMIAR_SOM_RMS_MAX = 200
LIMIAR_VIB_MAX = 50


def features(janela):
    f = dict(janela)
    rpm, rms, pico, vib = (janela.get(k) for k in CANAIS)
    f["crista"] = pico / rms if pico is not None and rms is not None and rms > 0 else None
    f["vib_por_rev"] = vib / (rpm / 60.0) if vib is not None and rpm is not None and rpm > DEGRAU_RPM else None
    f["delta_rpm"] = None
    return f


def features_serie(janelas):
    fs = [features(j) for j in janelas]
    for i in range(1, len(fs)):
        a, b = fs[i - 1].get("rpm"), fs[i].get("rpm")
        if a is not None and b is not None:
            fs[i]["delta_rpm"] = b - a
    return fs


def saude(serie, i, motor_girando):
    ausente, travado, fora = [], [], []
    for c in CANAIS:
        if i >= 2 and all(serie[k].get(c) is None for k in (i - 2, i - 1, i)):
            ausente.append(c)
        if motor_girando and i >= 4:
            v = [serie[k].get(c) for k in range(i - 4, i + 1)]
            if v[0] is not None and all(x == v[0] for x in v):
                travado.append(c)
        x = serie[i].get(c)
        lo, hi = FAIXA_FISICA[c]
        if x is not None and not lo <= x <= hi:
            fora.append(c)
    return {"canal_ausente": ausente, "valor_travado": travado, "fora_da_faixa_fisica": fora}


def _sd(x, piso):
    s = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    return max(s, piso)


class Baseline:
    def __init__(self, janelas):
        if not janelas:
            raise ValueError("baseline vazio")
        for j in janelas:
            for c in BASE_CANAIS:
                if j.get(c) is None or j[c] != j[c]:
                    raise ValueError("canal invalido: " + c)
        col = {c: np.array([j[c] for j in janelas], dtype=float) for c in BASE_CANAIS}
        self.media = {c: float(col[c].mean()) for c in BASE_CANAIS}
        self.sd = {c: _sd(col[c], PISO[c]) for c in BASE_CANAIS}
        n = len(janelas)
        X = np.column_stack([np.ones(n), col["vib"], col["rpm"]])
        self.coef_som = np.linalg.lstsq(X, col["som_rms"], rcond=None)[0]
        res = col["som_rms"] - X @ self.coef_som
        self.sd_res_som = _sd(res, PISO["som_rms"])
        X2 = np.column_stack([np.ones(n), col["som_rms"]])
        self.coef_vib = np.linalg.lstsq(X2, col["vib"], rcond=None)[0]
        res2 = col["vib"] - X2 @ self.coef_vib
        self.sd_res_vib = _sd(res2, PISO["vib"])

    def z(self, janela):
        return {c: (janela[c] - self.media[c]) / self.sd[c] for c in ("rpm", "som_rms", "vib")}

    def residuos(self, janela):
        a, b, c = self.coef_som
        pred_som = a + b * janela["vib"] + c * janela["rpm"]
        a2, b2 = self.coef_vib
        pred_vib = a2 + b2 * janela["som_rms"]
        return {
            "som_rms": (janela["som_rms"] - pred_som) / self.sd_res_som,
            "vib": (janela["vib"] - pred_vib) / self.sd_res_vib,
        }


def tipar(janela, baseline):
    """Tipa uma janela. Contrato: rpm, som_rms e vib devem ser numeros validos; None ou NaN levanta
    ValueError("canal invalido: <nome>"). Quem chama deve checar saude() antes (canal ausente nao e' normal)."""
    for c in BASE_CANAIS:
        v = janela.get(c)
        if v is None or v != v:
            raise ValueError("canal invalido: " + c)
    z = baseline.z(janela)
    res = baseline.residuos(janela)
    rpm, som, vib = janela["rpm"], janela["som_rms"], janela["vib"]
    mu, sd = baseline.media, baseline.sd

    def sai(classe, por_que):
        return {"classe": classe, "por_que": por_que, "z": z, "residuos": res}

    if rpm < DEGRAU_RPM and som > mu["som_rms"] - sd["som_rms"]:
        return sai("inconsistencia", "rpm zero com som de motor: palheta ou sensor optico? (rpm=%.0f, som_rms=%.1f)" % (rpm, som))
    if rpm < DEGRAU_RPM and vib > mu["vib"] + 3 * sd["vib"]:
        return sai("inconsistencia", "vibracao sem rotacao: mola ou ruido? (rpm=%.0f, vib=%.1f)" % (rpm, vib))
    fora = [c for c in ("rpm", "vib") if abs(z[c]) > LIMIAR_Z]
    if fora:
        partes = ", ".join("%s=%.1f (z=%+.1f)" % (c, janela[c], z[c]) for c in fora)
        return sai("anomalia", "canal fora da distribuicao: " + partes)
    cruz = [c for c in ("som_rms", "vib") if abs(res[c]) > LIMIAR_Z]
    if cruz:
        partes = ", ".join("%s=%.1f (residuo=%+.1f sigma)" % (c, janela[c], res[c]) for c in cruz)
        return sai("inconsistencia", "som nao bate com vibracao e rotacao: " + partes)
    return sai("normal", "dentro do esperado")


def lane_limiar(janela):
    return bool(janela["rpm"] < LIMIAR_RPM_MIN or janela["som_rms"] > LIMIAR_SOM_RMS_MAX or janela["vib"] > LIMIAR_VIB_MAX)


def lane_mega(linha):
    return linha.get("estado_mega") == "ALERTA"


def lane_ia(janela, baseline):
    t = tipar(janela, baseline)
    t["disparou"] = t["classe"] != "normal"
    return t


def avaliar(janelas, rotulos, alarmes, guarda=2, rotulos_guarda=None):
    """Deteccao mede atraso do inicio do episodio (a guarda nao se aplica: atraso 0 e 1 contam).
    A guarda so tira de falsos_alarmes/alarmes_em_s as janelas em [k-guarda, k+guarda] para cada troca de rotulo
    na janela k (a parte depois de k perdoa o atraso do apertar de tecla).
    `rotulos_guarda` (opcional): rotulos de verdade do operador, quando `rotulos` ja veio com janelas excluidas
    (x) pela conta; so as trocas feitas pelo operador abrem guarda."""
    n = len(rotulos)
    rg = rotulos if rotulos_guarda is None else rotulos_guarda
    guardadas = set()
    for k in range(1, n):
        if rg[k] != rg[k - 1]:
            guardadas.update(range(max(0, k - guarda), min(n, k + guarda + 1)))
    episodios, falsos, em_s = [], 0, 0
    i = 0
    while i < n:
        r = rotulos[i]
        j = i
        while j < n and rotulos[j] == r:
            j += 1
        if r in ("a", "p", "m", "c"):
            prim = next((k for k in range(i, j) if alarmes[k]), None)
            episodios.append({"rotulo": r, "inicio": i, "detectado": prim is not None,
                              "atraso": None if prim is None else prim - i})
        elif r in ("n", "r", "s"):
            for k in range(i, j):
                if alarmes[k] and (k not in guardadas or r == "r"):  # r mede o falso alarme honesto: a guarda nao o perdoa
                    if r == "s":
                        em_s += 1
                    else:
                        falsos += 1
        i = j
    return {"episodios": episodios, "falsos_alarmes": falsos, "alarmes_em_s": em_s}
