"""Avaliacao headless das 3 faixas (limiar, mega, ia) contra os rotulos de uma sessao.

Uso: python -I sinais/avaliar.py <sessao/> [--baseline-max N]
Le sinais.csv e rotulos.csv; escreve detectores.jsonl e avaliacao.json na propria pasta e imprime um resumo ASCII.

Convencao de rotulos (registrador.py): uma linha de rotulos.csv guarda a ULTIMA janela_mega vista ao apertar a tecla.
O rotulo vale para as janelas da MESMA epoca com janela_mega > esse valor, ate a proxima tecla. Janela vazia vale desde a
primeira janela da epoca. Cada epoca comeca sem rotulo ate a primeira tecla.

classe_final (contexto vence modelo): a faixa ia nunca ve o contexto e marca a parada comandada (s) como fora da
distribuicao. Se a janela esta em segmento s E a ia disparou, classe_final = "evento_esperado"; senao = ia.classe.
Sem rede, sem variaveis de ambiente. Texto de saida em ASCII.
"""
import os
import sys

# Com `python -I` o diretorio deste script nao entra no sys.path: inserimos explicitamente.
DIR_SINAIS = os.path.dirname(os.path.abspath(__file__))
if DIR_SINAIS not in sys.path:
    sys.path.insert(0, DIR_SINAIS)

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import unicodedata  # noqa: E402

import metricas  # noqa: E402

JANELA_CALIB = 34        # primeira janela pos-calibracao do Mega (30 + 3 de aquecimento + 1)
BASELINE_MIN = 15        # janelas n minimas para ajustar o Baseline
FAIXAS = ("limiar", "mega", "ia")
CANAIS_IA = ("rpm", "som_rms", "vib")
EXCLUIDO_POS = "exclu\u00eddo: r\u00f3tulo depois do disparo (aperte a tecla antes do gesto)"
EXCLUIDO_FA = "exclu\u00eddo: o Mega disparou com o r\u00f3tulo ainda em normal (falso alarme, ou tecla apertada tarde: aperte antes do gesto; resete o Mega)"
NAO_AVALIOU = "n\u00e3o avaliou (sem baseline)"
AVISO_SIMULADO = "SIMULADO: smoke test do pipeline, nao prova de nada."


def _num(txt):
    if txt is None or txt.strip() == "":
        return None
    try:
        v = float(txt)
    except ValueError:
        return None
    return v if v == v else None


def expandir_rotulos(janelas, teclas):
    """janelas: lista de dicts com janela_mega (de UMA epoca, em ordem). teclas: [(janela_mega|None, rotulo)] na ordem.
    Devolve um rotulo (ou None) por janela."""
    out = [None] * len(janelas)
    for jm, rot in teclas:
        for i, j in enumerate(janelas):
            if jm is None or j["janela_mega"] > jm:
                out[i] = rot
    return out


def carregar(sessao):
    with open(os.path.join(sessao, "sinais.csv"), newline="", encoding="utf-8") as f:
        linhas = []
        for r in csv.DictReader(f):
            linhas.append({
                "t_s": _num(r["t_s"]), "epoca": int(r["epoca"]), "janela_mega": int(r["janela_mega"]),
                "rpm": _num(r["rpm"]), "som_rms": _num(r["som_rms"]), "som_pico": _num(r["som_pico"]),
                "vib": _num(r["vib"]), "score_mega": _num(r["score_mega"]), "estado_mega": r["estado_mega"] or None,
            })
    teclas = {}
    with open(os.path.join(sessao, "rotulos.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            jm = r["janela_mega"].strip()
            teclas.setdefault(int(r["epoca"]), []).append((int(jm) if jm else None, r["rotulo"]))
    por_epoca = {}
    for l in linhas:
        por_epoca.setdefault(l["epoca"], []).append(l)
    epocas = sorted(por_epoca)
    manifesto = {}
    try:
        with open(os.path.join(sessao, "manifesto.json"), encoding="utf-8") as f:
            manifesto = json.load(f)
    except OSError:
        pass
    return {"epocas": epocas, "janelas_por_epoca": [por_epoca[e] for e in epocas],
            "rotulos_por_janela": [expandir_rotulos(por_epoca[e], teclas.get(e, [])) for e in epocas],
            "simulado": bool(manifesto.get("simulado"))}


def _valida(j):
    return all(j.get(c) is not None for c in CANAIS_IA)


def _janelas_baseline(janelas, rotulos, maximo, trip=None):
    """Janelas n OU sem rotulo (None) pos-calibracao, antes do primeiro rotulo que nao seja n. Sem rotulo vale
    como normal: o operador que esqueceu o n nao desliga a ia. Devolve indices (so janelas com canais validos)."""
    idx = []
    for i, (j, r) in enumerate(zip(janelas, rotulos)):
        if r not in (None, "n") or (trip is not None and i >= trip):
            break   # o baseline para no primeiro rotulo de falha e na janela do disparo (depois dela o motor esta parado)
        if j["janela_mega"] >= JANELA_CALIB and _valida(j):
            idx.append(i)
    if maximo:
        idx = idx[:maximo]
    return idx


def processar_epoca(janelas, rotulos, baseline_max=0):
    serie = metricas.features_serie(janelas)
    trip = next((i for i, j in enumerate(janelas) if j["estado_mega"] == "ALERTA"), None)
    idx_base = _janelas_baseline(janelas, rotulos, baseline_max, trip)
    insuficiente = len(idx_base) < BASELINE_MIN
    base = None if insuficiente else metricas.Baseline([janelas[i] for i in idx_base])
    fim_base = idx_base[-1] if idx_base and not insuficiente else None
    linhas = []
    for i, j in enumerate(janelas):
        girando = j["rpm"] is not None and j["rpm"] >= metricas.DEGRAU_RPM
        sa = metricas.saude(serie, i, girando)
        ia = None
        if base is None:
            ia = {"avaliada": False, "disparou": False, "classe": "sem_baseline",
                  "por_que": "sem baseline: menos de %d janelas normais depois da calibracao" % BASELINE_MIN}
        elif i > fim_base:
            faltam = [c for c in CANAIS_IA if j[c] is None or c in sa["canal_ausente"]]
            if faltam:
                ia = {"avaliada": True, "disparou": False, "classe": "canal_ausente",
                      "por_que": "canal sem leitura: " + ", ".join(faltam) + " (nao tipado)"}
            else:
                t = metricas.lane_ia(j, base)
                ia = {"avaliada": True, "disparou": bool(t["disparou"]), "classe": t["classe"], "por_que": t["por_que"]}
        if ia is None or not ia["avaliada"]:
            final = None
        elif rotulos[i] == "s" and ia["disparou"]:
            final = "evento_esperado"
        else:
            final = ia["classe"]
        linhas.append({
            "t_s": j["t_s"], "epoca": j["epoca"], "janela_mega": j["janela_mega"], "rotulo": rotulos[i],
            "limiar": bool(_valida(j) and metricas.lane_limiar(j)),
            "mega": bool(metricas.lane_mega(j)),
            "ia": ia, "classe_final": final, "saude": sa, "pos_disparo": trip is not None and i > trip,
        })
    info = {"epoca": janelas[0]["epoca"], "janelas": len(janelas), "baseline_n": len(idx_base),
            "baseline_insuficiente": insuficiente, "baseline_ate_janela": None if fim_base is None else janelas[fim_base]["janela_mega"],
            "disparo_mega_janela": None if trip is None else janelas[trip]["janela_mega"],
            "disparo_em_normal": trip is not None and rotulos[trip] in (None, "n")}
    return linhas, info


def _episodios_so_pos_disparo(rotulos, rot_conta):
    """Rotulos de falha (a/p/m/c) cujo episodio inteiro caiu depois do disparo do Mega (tecla tarde demais)."""
    out, i, n = [], 0, len(rotulos)
    while i < n:
        j = i
        while j < n and rotulos[j] == rotulos[i]:
            j += 1
        if rotulos[i] in ("a", "p", "m", "c") and all(r == "x" for r in rot_conta[i:j]):
            out.append((rotulos[i], i))
        i = j
    return out


def _contagem(valores):
    c = {}
    for v in valores:
        c[v] = c.get(v, 0) + 1
    return c


def avaliar_sessao(dados, baseline_max=0):
    todas, infos, eventos, contexto = [], [], [], []
    sem_baseline = 0
    por_faixa = {f: {"episodios": [], "falsos_alarmes": 0, "alarmes_em_s": 0} for f in FAIXAS}
    for janelas, rotulos in zip(dados["janelas_por_epoca"], dados["rotulos_por_janela"]):
        linhas, info = processar_epoca(janelas, rotulos, baseline_max)
        todas.extend(linhas)
        infos.append(info)
        alarmes = {
            "limiar": [l["limiar"] for l in linhas],
            "mega": [l["mega"] for l in linhas],
            "ia": [bool(l["ia"] and l["ia"]["disparou"]) for l in linhas],
        }
        # Depois do disparo do Mega o rele B corta o motor: essas janelas viram x so na CONTA (o rotulo gravado
        # continua o do operador). A janela do ALERTA ainda conta; o atraso continua medido do inicio do episodio.
        rot_conta = ["x" if l["pos_disparo"] else r for l, r in zip(linhas, rotulos)]
        excl = _episodios_so_pos_disparo(rotulos, rot_conta)
        info["episodios_pos_disparo"] = [r for r, _ in excl]
        for r, i0 in excl:
            eventos.append({"epoca": info["epoca"], "rotulo": r, "janela_mega_inicio": janelas[i0]["janela_mega"],
                            "excluido": True, "resultado": EXCLUIDO_FA if info["disparo_em_normal"] else EXCLUIDO_POS})
        res = {f: metricas.avaliar(janelas, rot_conta, alarmes[f], rotulos_guarda=rotulos) for f in FAIXAS}
        ia_avaliou = not info["baseline_insuficiente"]
        for f in FAIXAS:
            por_faixa[f]["falsos_alarmes"] += res[f]["falsos_alarmes"]
            por_faixa[f]["alarmes_em_s"] += res[f]["alarmes_em_s"]
            if f != "ia" or ia_avaliou:
                por_faixa[f]["episodios"].extend(dict(e, epoca=info["epoca"]) for e in res[f]["episodios"])
            else:
                sem_baseline += len(res[f]["episodios"])
        for k, e in enumerate(res["ia"]["episodios"]):
            ev = {"epoca": info["epoca"], "rotulo": e["rotulo"], "janela_mega_inicio": janelas[e["inicio"]]["janela_mega"]}
            for f in FAIXAS:
                x = res[f]["episodios"][k]
                ev[f] = {"detectado": x["detectado"], "atraso": x["atraso"]}
            if not ia_avaliou:
                ev["ia"].update(avaliou=False, resultado=NAO_AVALIOU, classe=None, por_que=None, janela_mega_primeiro_alarme=None)
                ev["classe_final"] = None
                eventos.append(ev)
                continue
            ev["ia"]["avaliou"] = True
            if e["detectado"]:
                l = linhas[e["inicio"] + e["atraso"]]
                ev["ia"].update(classe=l["ia"]["classe"], por_que=l["ia"]["por_que"], janela_mega_primeiro_alarme=l["janela_mega"])
                ev["classe_final"] = l["classe_final"]
            else:
                ev["ia"].update(classe=None, por_que=None, janela_mega_primeiro_alarme=None)
                ev["classe_final"] = None
            eventos.append(ev)
        # segmentos de contexto (s e r): o que cada faixa viu e o que o publico ve (classe_final)
        i, n = 0, len(rotulos)
        while i < n:
            j = i
            while j < n and rotulos[j] == rotulos[i]:
                j += 1
            if rotulos[i] in ("s", "r"):
                seg = [l for l in linhas[i:j] if not l["pos_disparo"]]   # so antes do disparo: depois dele o motor esta parado
                if not seg:
                    i = j
                    continue
                contexto.append({
                    "epoca": info["epoca"], "rotulo": rotulos[i], "janela_mega_inicio": seg[0]["janela_mega"], "janelas": len(seg),
                    "janelas_marcadas": j - i,
                    "limiar_alarmes": sum(l["limiar"] for l in seg), "mega_alarmes": sum(l["mega"] for l in seg),
                    "ia_avaliadas": sum(bool(l["ia"] and l["ia"]["avaliada"]) for l in seg),
                    "ia_alarmes": sum(bool(l["ia"] and l["ia"]["disparou"]) for l in seg),
                    "classe_final": _contagem(l["classe_final"] for l in seg if l["classe_final"] is not None),
                })
            i = j
    faixas = {}
    for f in FAIXAS:
        eps = por_faixa[f]["episodios"]
        atrasos = [e["atraso"] for e in eps if e["detectado"]]
        faixas[f] = {"falsos_alarmes": por_faixa[f]["falsos_alarmes"], "alarmes_em_s": por_faixa[f]["alarmes_em_s"],
                     "episodios_sem_baseline": sem_baseline if f == "ia" else 0, "episodios_total": len(eps), "episodios_detectados": sum(e["detectado"] for e in eps),
                     "atraso_medio": (sum(atrasos) / len(atrasos)) if atrasos else None, "episodios": eps}
    avaliacao = {
        "simulado": dados["simulado"], "aviso": AVISO_SIMULADO if dados["simulado"] else None,
        "janelas": len(todas), "epocas": infos, "faixas": faixas, "eventos": eventos, "segmentos_contexto": contexto,
        "classe_final_em_s": _contagem(l["classe_final"] for l in todas if l["rotulo"] == "s"),
    }
    return todas, avaliacao


def resumo(av):
    L = []
    if av["simulado"]:
        L.append("*** " + AVISO_SIMULADO + " ***")
    L.append("janelas: %d | epocas: %d | baseline insuficiente: %d" % (
        av["janelas"], len(av["epocas"]), sum(e["baseline_insuficiente"] for e in av["epocas"])))
    L.append("")
    L.append("por evento (a/p/m/c)      limiar    mega      ia                 classe ia       classe_final")
    def cel(x):
        if x.get("avaliou") is False:
            return "n/aval"
        return "-" if not x["detectado"] else "+%d" % x["atraso"]
    for e in av["eventos"]:
        if e.get("excluido"):
            L.append("ep%02d %s (janela %3d)       %s" % (e["epoca"], e["rotulo"], e["janela_mega_inicio"], unicodedata.normalize("NFKD", e["resultado"]).encode("ascii", "ignore").decode()))
            continue
        L.append("ep%02d %s (janela %3d)       %-8s  %-8s  %-8s           %-14s  %s" % (
            e["epoca"], e["rotulo"], e["janela_mega_inicio"], cel(e["limiar"]), cel(e["mega"]), cel(e["ia"]),
            e["ia"]["classe"] or "-", e["classe_final"] or "-"))
    L.append("(+k = detectado com atraso de k janelas; - = nao detectado; n/aval = nao avaliou (sem baseline))")
    tr = [e for e in av["epocas"] if e.get("disparo_mega_janela") is not None]
    if tr:
        L.append("Mega travou em %d epoca(s) (%s): as janelas depois do disparo (rele B cortou o motor) ficam fora da conta" % (
            len(tr), ", ".join("ep%02d:j%d" % (e["epoca"], e["disparo_mega_janela"]) for e in tr)))
    for e in tr:
        if e["episodios_pos_disparo"]:
            L.append("ep%02d: episodio(s) marcado(s) so depois do disparo, fora da conta: %s" % (e["epoca"], ",".join(e["episodios_pos_disparo"])))
    L.append("")
    L.append("faixa     detectados  atraso medio  falsos alarmes (n/r)  alarmes em s")
    for f in FAIXAS:
        x = av["faixas"][f]
        am = "-" if x["atraso_medio"] is None else "%.1f" % x["atraso_medio"]
        L.append("%-8s  %3d/%-3d     %-12s  %-20d  %d" % (f, x["episodios_detectados"], x["episodios_total"], am, x["falsos_alarmes"], x["alarmes_em_s"]))
    L.append("")
    L.append("segmentos de contexto (s = parada pelo app, r = ruido da sala)")
    for c in av["segmentos_contexto"]:
        L.append("ep%02d %s: %d janelas antes do disparo | limiar %d | mega %d | ia %d/%d | classe_final %s" % (
            c["epoca"], c["rotulo"], c["janelas"], c["limiar_alarmes"], c["mega_alarmes"], c["ia_alarmes"], c["ia_avaliadas"],
            json.dumps(c["classe_final"], sort_keys=True)))
    s = av["classe_final_em_s"]
    ruim = s.get("anomalia", 0) + s.get("inconsistencia", 0)
    L.append("classe_final nas janelas s: %s -> anomalia/inconsistencia: %d" % (json.dumps(s, sort_keys=True), ruim))
    return "\n".join(L)


def escrever(sessao, linhas, avaliacao):
    with open(os.path.join(sessao, "detectores.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for l in linhas:
            f.write(json.dumps(l, ensure_ascii=True, sort_keys=True) + "\n")
    with open(os.path.join(sessao, "avaliacao.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(avaliacao, f, ensure_ascii=True, indent=1, sort_keys=True)
        f.write("\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="avaliar.py", description=__doc__.split("\n")[0])
    p.add_argument("sessao")
    p.add_argument("--baseline-max", type=int, default=0,
                   help="limita o baseline as N primeiras janelas n (0 = todas ate o primeiro rotulo nao-n); "
                        "serve para testar falsos alarmes fora da amostra em sessoes so de n")
    a = p.parse_args(argv)
    if a.baseline_max < 0:
        p.error("--baseline-max deve ser >= 0 (0 = sem teto)")
    dados = carregar(a.sessao)
    linhas, av = avaliar_sessao(dados, a.baseline_max)
    escrever(a.sessao, linhas, av)
    print(resumo(av))
    return 0


if __name__ == "__main__":
    sys.exit(main())
