"""Gera colab/m7-esteira-plano-e-testes.ipynb a partir dos arquivos do repositorio (nada e redigitado).

Uso (na raiz do repositorio):  python3 colab/gerar_notebook.py
Precisa de nbformat e de clang (roda a co-simulacao de host do gemeo para gerar a serial de exemplo).
Le: wokwi-mega-esteira-ky/*, evidencias/2026-11-0[89]-*, e confere os sha256 do gemeo contra a evidencia do projeto salvo.
"""
import base64
import hashlib
import os
import re
import subprocess
import sys
import tempfile

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "colab", "m7-esteira-plano-e-testes.ipynb")
GEMEO = ("sketch.ino", "diagram.json", "esteira.chip.c", "esteira.chip.json")
WOKWI_URL = "https://wokwi.com/projects/480213362190861313"


def ler(rel, modo="r"):
    with open(os.path.join(RAIZ, rel), modo, **({} if "b" in modo else {"encoding": "utf-8"})) as f:
        return f.read()


def sha(rel):
    return hashlib.sha256(ler(rel, "rb")).hexdigest()


# ---------------------------------------------------------------- fontes
ev_wokwi = ler("evidencias/2026-11-09-wokwi-projeto-salvo.txt")
esperado = dict(re.findall(r"^\s+(\S+)\s+([0-9a-f]{64})", ev_wokwi, re.M))
assert set(esperado) == set(GEMEO), esperado
for nome in GEMEO:
    real = sha("wokwi-mega-esteira-ky/" + nome)
    assert real == esperado[nome], "sha256 do repositorio difere da evidencia: %s" % nome
assert sha("arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino") == esperado["sketch.ino"], "gemeo quebrado"

ev_etapa1 = ler("evidencias/2026-11-09-bancada-etapa-1.txt")
ev_etapa2 = ler("evidencias/2026-11-09-bancada-etapa-2.txt")
ev_wokwi_t15 = ler("evidencias/2026-11-08-t15-wokwi-esteira.txt")
png = base64.b64encode(ler("evidencias/2026-11-09-diagrama-ligacao.png", "rb")).decode("ascii")

# serial completa do gemeo: co-simulacao de host (sketch.ino + esteira.chip.c reais), cenario atrito, semente 1
with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, TMPDIR=tmp)
    subprocess.run(["sh", os.path.join(RAIZ, "wokwi-mega-esteira-ky/teste-host/rodar.sh"), "atrito"],
                   check=True, env=env, stdout=subprocess.DEVNULL)
    with open(os.path.join(tmp, "gemeo-m7-cosim", "atrito.txt"), encoding="utf-8") as f:
        serial_cosim = f.read()
assert "# CONFERE ok" in serial_cosim and "AUTO-TESTE: 17/17 -> PASS" in serial_cosim


def linhas(texto, padrao):
    return "\n".join(l for l in texto.splitlines() if re.search(padrao, l))


# ---------------------------------------------------------------- celulas
celulas = []


def md(texto, **kw):
    celulas.append(new_markdown_cell(texto.strip("\n"), **kw))


def code(texto):
    celulas.append(new_code_cell(texto.strip("\n")))


def writefile(caminho, conteudo):
    # o conteudo vai byte a byte (com o \n final); o sha256 e conferido mais abaixo no notebook
    celulas.append(new_code_cell("%%writefile " + caminho + "\n" + conteudo))


md("""
# M7 — esteira instrumentada: plano de construção e testes (bancada + gêmeo Wokwi)

**VOCAID DEEP · Masterclass 12/11/2026.** Este notebook junta, num só lugar, o que a turma precisa para reproduzir o circuito M7: o plano, as peças e os pinos, as regras de segurança, as fases de teste com o status real, o código do gêmeo Wokwi e uma análise executável do z-score com a mesma regra do firmware.

**Status real em 09/11/2026:** etapas **1 e 2 PASSARAM** na placa real. As etapas 0, 3, 4, 5, 5b, 6 e 7 estão **pendentes**. Onde a bancada ainda não mediu, o notebook diz **lacuna** e não inventa número.

Fontes no repositório `masterclass-12-11`: `BANCADA-ENSAIO.md`, `arduino-mega-esteira-ky/`, `esp8266-esteira-app/`, `wokwi-mega-esteira-ky/`, `evidencias/2026-11-0[89]-*` e `sinais/`. O notebook foi gerado por `colab/gerar_notebook.py`, que lê esses arquivos (nada foi redigitado).

**Como usar no Colab:** *Ambiente de execução → Executar tudo*. Não precisa de hardware nem de internet além do próprio Colab: os arquivos do gêmeo e as seriais de exemplo são gravados pelas células.
""")

md("""
## 1. Visão geral

Três sensores baratos (óptico, som e vibração) vigiam um motor DC com volante. O Arduino Mega transforma cada janela de 1 s num **escore de saúde calibrado** e corta o motor por um relé quando o escore sai do normal.

- **O E físico em série.** O motor só gira se o **relé A** (NodeMCU: "o app aprovou", `esteira: ligada` no `meta` do artigo) **E** o **relé B** (Mega: "a IA não disparou") estiverem fechados. Os dois contatos ficam em série no caminho de potência: qualquer um que abra corta o motor, sem software no meio.
- **z-score calibrado.** 3 janelas de aquecimento são descartadas e 30 janelas calibram a média e o desvio de cada canal (rpm, som_rms, vib). Cada desvio tem um piso: rpm 60, som 3 e vib 2. Depois, `z = (x − média) / desvio` por canal e `score = max |z|`.
- **ALERTA travado.** Dispara com `score > 3,0` (estrito) em **2 janelas seguidas**: o relé B abre, o LED vermelho acende e o buzzer toca. Não há rearme automático; só o reset da placa rearma (e recalibra, uns 33 s).
- **SUSPEITA.** Se o rpm médio da calibração ficar abaixo de 60 (motor parado), o Mega corta o motor e não arma o ALERTA até o reset.

Não é rede neural: é estatística calibrada. O upgrade seria um MLP int8, como no módulo de impacto.

Diagrama de ligação (`evidencias/2026-11-09-diagrama-ligacao.png`):

![diagrama de ligação do M7](attachment:diagrama-ligacao.png)
""", attachments={"diagrama-ligacao.png": {"image/png": png}})

md("""
## 2. Peças, pinos e segurança

### Peças e pinos

| Peça | Liga em | Observação | Situação em 09/11 |
|---|---|---|---|
| Arduino Mega 2560 | USB do computador | firmware `arduino-mega-esteira-ky.ino` (= `sketch.ino` do gêmeo) | **testado** (etapa 1) |
| KY-010 (óptico), `S` | D2 (INT4) | 1 aleta de papel = 1 pulso por volta; guardas de 200 µs e 2 ms | **falta** |
| KY-037 (som), `AO` | A0 | amostrado a ~1 kHz; trimpot no meio da faixa | lacuna (etapa 3) |
| KY-002 (vibração), `S` | D3 (INT5) | conta todas as bordas (1 evento = 2 bordas) | lacuna (etapa 3) |
| Relé B: HW-482 no lugar do KY-019, `S` / `+` / `-` | D7 / 5 V / GND | ativo em ALTO (`RELE_ATIVO_BAIXO = false`); contato **COM–NO** | **testado** (etapa 2) |
| LED verde (OK) | D4 + 220 Ω | pisca na calibração, fixo no NORMAL | lacuna (etapa 3) |
| LED vermelho (ALERTA) | D5 + 220 Ω | | lacuna |
| Buzzer ativo | D6 | | lacuna |
| NodeMCU ESP8266 + módulo do relé A | IN no D1 (GPIO5); VCC no 3V3 ou VIN; GND comum | `RELE_ATIVO_BAIXO = true` por padrão; contato **COM–NO** | lacuna (etapa 4) |
| NPN 2N2222 ou BC547 + 1 kΩ (base) + 10 kΩ (base–emissor) | entre D1 e o IN do relé A | só se o relé A não clicar com 3,3 V; aí `RELE_ATIVO_BAIXO = false` | se precisar |
| Motor Akiyama AK280 + volante de latão | adaptador externo, via relé A e relé B | parte em 5–6 V, roda em 9 V, máx. 12 V | lacuna (etapa 5) |
| Adaptador externo ≥ 1 A | potência do motor | ajustado no **menor** valor no 1º teste | **falta** |
| Diodo 1N4007 | terminais do motor, faixa no + | absorve o pico de abertura do relé | **falta** |
| Capacitor cerâmico 100 nF | terminais do motor | corta o ruído das escovas | **falta** |
| Aleta de papel 5–15 mm | aro do volante | nunca mais da metade do aro | lacuna |
| Multímetro, óculos, grampo, copo ou caixa transparente | — | etapa 0 | lacuna |
| (5b, opcional) KY-008 laser + KY-018 fotorresistor | 5 V / GND; `S` do KY-018 no D2 | barreira de laser no lugar do KY-010 | opcional |

"Falta" = peça que a sessão da bancada registrou como ainda não disponível em 09/11. "Lacuna" = ainda não conferido em bancada.

### Regras de segurança (não negociáveis)

1. **O motor só sai do adaptador externo.** Nunca no 5 V do Mega, nunca no trilho AMS1117 da YwRobot: a corrente de partida derruba o trilho, reinicia o Mega e pode queimar o regulador.
2. **GND comum:** Mega, NodeMCU, adaptador (−) e os módulos no mesmo GND.
3. **COM/NO, nunca NC**, nos dois relés. NC fecharia o motor justamente com o relé desligado.
4. **Relé A em 3,3 V:** o GPIO do NodeMCU pode não acionar um módulo de 5 V. Se não clicar nas duas polaridades, use o NPN (tabela acima) e grave com `RELE_ATIVO_BAIXO = false`.
5. **Motor desconectado** nas etapas 1–4. Ele só entra na etapa 5, depois das duas checagens de relé.
6. **Diodo e capacitor** nos terminais do motor. Se o Mega reiniciar quando o motor parte, o problema é a alimentação ou o capacitor, não o sketch.
7. **Mecânica:** óculos, volante preso por grampo e coberto, sem mangas nem cabelo soltos, dedos longe do eixo, primeiro teste na menor tensão.
8. **Laser (5b):** nunca nos olhos nem na lente da câmera.

```
adaptador externo (+) → COM–NO do relé A (NodeMCU) → COM–NO do relé B (Mega, D7) → AK280 (+)
adaptador externo (−) → AK280 (−) → GND do Mega e do NodeMCU (GND comum)
```
""")

# ---------------------------------------------------------------- fases
md("""
## 3. Fases de teste, etapa por etapa

Roteiro de `BANCADA-ENSAIO.md`. **Não pule etapas.** Os comandos rodam na raiz do repositório; `<MEGA>` e `<NODE>` são as portas que aparecem em `arduino-cli board list`. Só um programa por porta: feche o Serial Monitor da IDE antes do `upload` e antes do registrador.

| Etapa | O quê | Status em 09/11/2026 |
|---|---|---|
| 0 | preparo, sem energia | **pendente** (faltam a fonte ≥ 1 A, o 1N4007 e o 100 nF) |
| 1 | Mega sozinho no USB | **PASSOU** (08:55; 17/17, `# SUSPEITA` 33 s depois do cabeçalho) |
| 2 | relé B no D7, motor desconectado | **PASSOU** (11:20; HW-482 ativo em ALTO; COM–NO abre em 33,1 s) |
| 3 | sensores no Mega, motor desconectado | **pendente** (falta o KY-010) |
| 4 | NodeMCU e relé A, motor desconectado | **pendente** |
| 5 | motor em baixa tensão, A e B em série | **pendente** |
| 5b | (opcional) rpm por barreira de laser | **pendente** |
| 6 | validade dos gestos `a m p s r` | **pendente** |
| 7 | shakedown e gravação do ensaio | **pendente** |
""")

md("""
### Etapa 0 — preparo (sem energia) · **pendente**

- Óculos, volante preso por grampo e coberto, adaptador externo ≥ 1 A no **menor** valor (5–6 V).
- Diodo 1N4007 nos terminais do AK280 (faixa no +) e capacitor cerâmico de 100 nF nos terminais.
- Aleta de papel de 5–15 mm no aro, passando pela fenda do KY-010 sem raspar.
- Multímetro em continuidade.

**Lacuna:** em 09/11 ainda faltavam o KY-010, a fonte externa ≥ 1 A, o 1N4007 e o capacitor de 100 nF.
""")

md("""
### Etapa 1 — Mega sozinho no USB (nada nos pinos) · **PASSOU em 09/11**

```bash
arduino-cli upload --fqbn arduino:avr:mega -p <MEGA> arduino-mega-esteira-ky
arduino-cli monitor -p <MEGA> -c baudrate=115200
```

**Passa se** a serial mostrar `AUTO-TESTE: 17/17 -> PASS`, a linha de método, o cabeçalho CSV e, uns 33 s depois, `# SUSPEITA` (sem motor, isso é o esperado). **Pare** se o autoteste falhar ou a serial sair com lixo (baud ou porta errados).

Serial real, em trechos (`evidencias/2026-11-09-bancada-etapa-1.txt`; coluna 1 = epoch no Mac; a serial completa vai para a seção 5):

```
%s
```

O `som_rms` de ~19 é o A0 flutuando, sem nada ligado; **não é medida de sensor**. A célula da seção 5 recalcula o tempo até a `# SUSPEITA` a partir desta serial.
""" % linhas(ev_etapa1, r"^(Etapa|Placa|Firmware)|AUTO-TESTE: |janela,rpm|^\d+\.\d (1|2|3|4|32|33|34),|# (metodo|calibrado|SUSPEITA)"))

md("""
### Etapa 2 — relé B no Mega, motor DESCONECTADO · **PASSOU em 09/11**

Ligação: `S` no D7, `+` no 5 V, `-` no GND. Multímetro em continuidade entre **COM e NO**. Nada no contato.

| Momento | COM–NO esperado |
|---|---|
| segurando RESET, boot e AUTO-TESTE | **ABERTO** |
| depois do cabeçalho CSV | **FECHADO** (clique) |
| depois do `# SUSPEITA` (~33 s) | **ABERTO** de novo |

**Pare** se algum estado sair invertido: troque `RELE_ATIVO_BAIXO`, regrave e repita a tabela inteira. Use NO, nunca NC.

Resultado real (`evidencias/2026-11-09-bancada-etapa-2.txt`):

```
%s
```

Lição da bancada: o LED do módulo acendia com o `+` do relé no GND, ou seja, **LED aceso não prova relé fechado**. Confira sempre com o multímetro.
""" % linhas(ev_etapa2, r"^(Etapa|Ligacao|Firmware|Resultado)|^\| |^- |# (calibrado|SUSPEITA)"))

md("""
### Etapa 3 — sensores no Mega, motor DESCONECTADO · **pendente**

Ligação: KY-010 `S` no D2, KY-037 `AO` no A0, KY-002 `S` no D3; `-` no GND e `+` (ou o pino do meio) no 5 V. LEDs no D4 (verde) e no D5 (vermelho) com 220 Ω, buzzer no D6.

```bash
sinais/.venv/bin/python -I sinais/registrador.py --serial <MEGA> --saida sinais/sessoes/teste-sensores
```

Durante AQUECENDO e CALIBRANDO:

- **óptico:** papel pela fenda do KY-010 várias vezes por segundo → `rpm` sobe de 0 (anote a polaridade do LED do módulo);
- **som:** palmas perto do KY-037 → `som_rms` e `som_pico` sobem (se ficar em 0 ou ~1023, ajuste o trimpot);
- **vibração:** tapinhas na mola do KY-002 → `vib` sobe.

**Serial esperada:** o mesmo cabeçalho da etapa 1; os valores dependem dos gestos. **Lacuna:** nenhum canal foi medido ainda. **Pare** se um canal ficar parado: fio ou pino errado.
""")

md("""
### Etapa 4 — NodeMCU e relé A, motor DESCONECTADO · **pendente**

**4a. Polaridade, sem rede.** `cp esp8266-esteira-app/segredos.exemplo.h esp8266-esteira-app/segredos.h` com um SSID **errado**, e grave:

```bash
arduino-cli upload --fqbn esp8266:esp8266:nodemcuv2 -p <NODE> esp8266-esteira-app
```

| Momento | COM–NO do relé A |
|---|---|
| `# rele A aberto: wi-fi fora` | **ABERTO** |
| segurando RESET | **ABERTO** |
| partida, antes da 1ª consulta | **ABERTO** |

**4b. Positivo, com rede.** Chave **dedicada** com escopo `research:read` somente; você mesmo preenche Wi-Fi (2,4 GHz), chave e workspace em `segredos.h` (no `.gitignore`; nunca cole a chave em chat). Serial esperada: `AUTO-TESTE: 43/43 -> PASS`. Commit `esteira: ligada` → em até 10 s `# rele A fechado` e continuidade; `esteira: desligada` → ABERTO.

**Pare** se houver continuidade em 4a (inverta `RELE_ATIVO_BAIXO`; se não clicar em nenhuma polaridade, use o NPN). `ntp falhou` → hotspot do celular; `http 401/403` → chave ou escopo; `http 429` → cota (cada boot gasta 120 consultas nos primeiros 20 min; 4 boots num dia estouram 1000/dia). **Lacuna:** o relé A não rodou no hardware.
""")

md("""
### Etapa 5 — motor em baixa tensão, A e B em série · **pendente**

```
adaptador (+) → COM–NO do relé A → COM–NO do relé B → AK280 (+)
adaptador (−) → AK280 (−) → GND do Mega e do NodeMCU (GND comum)
```

1. Commit `esteira: ligada` e espere `# rele A fechado` (segundo terminal: `arduino-cli monitor -p <NODE> -c baudrate=115200`).
2. Reset no Mega: o motor parte a 5–6 V. Espere `# calibrado:`. Nada tocando o volante.
3. Linhas `NORMAL` com `score` < 2; `rpm` estável e bem acima de 60, `som_rms` acima do silêncio, `vib` acima de 0.
4. Suba para 9 V só depois disso.

**Serial esperada (do gêmeo, é modelo e não medida):** `# calibrado: c0 media≈2000 … c1 media≈55 … c2 media≈5–6`, depois `NORMAL`. **Lacuna:** rpm, som e vib reais do AK280 não foram medidos; os alvos do chip do gêmeo são estimativas. **Pare** se o Mega reiniciar quando o motor parte (alimentação ou falta do capacitor) ou se aparecer `# SUSPEITA` com o motor girando.
""")

md("""
### Etapa 5b (opcional) — rpm por barreira de laser · **pendente**

Firmware e gêmeo não mudam: o Mega só conta as transições para LOW no D2. KY-008 (`S` no 5 V, `-` no GND, sempre aceso) e KY-018 (`+` 5 V, `-` GND, `S` no **D2**, no lugar do `S` do KY-010), meia-lua de papel no aro e canudo sobre o fotorresistor. Faça **depois** da etapa 5.

- Sem motor: papel no feixe → `rpm` sobe de 0. O `S` do KY-018 tem de cruzar o meio da faixa (> 3 V ↔ < 1,5 V no multímetro).
- Com motor, mesma tensão: 30 s de `rpm` com o laser e 30 s com o KY-010.
- **Passa** se a média do laser ficar a até 5 % da do KY-010, sem janelas em 0. **Não passou:** volte ao KY-010; o laser vira só efeito visual.

**Lacuna:** não testado. O fotorresistor responde em ~10–50 ms e meio período a ~2000 rpm dá ~15 ms: pode não acompanhar.
""")

md("""
### Etapa 6 — validade dos gestos (antes de gravar) · **pendente**

Cada gesto, uma vez, num reset novo, olhando a tela do registrador.

| Tecla | Gesto | Tem de acontecer | Se não acontecer |
|---|---|---|---|
| `a` | cotonete ou borracha num cabo no aro | `rpm` cai, som e vibração mudam → `ALERTA` em 2 janelas | toque mais firme; depois suba a tensão um degrau |
| `m` | fita sobre o microfone do KY-037 | só `som_*` cai | — |
| `p` | aleta solta ou dobrada | só `rpm` muda | se `rpm` e `vib` reais mudarem juntos, descarte o `p` |
| `s` | commit `esteira: desligada` | motor para; o Mega trava em `ALERTA` | — |
| `r` | barulho na sala, sem tocar a bancada | só som; é o falso alarme honesto | — |

**Referência do gêmeo (co-simulação de host, semente 1, falha na janela 40; modelo, não medida):** atrito → ALERTA na 41 (score 6,7); microfone → 41 (15,8); aleta → 41 (16,3); chave aberta → 41 (28,3); ruído da sala 100 → 41 (9,4). **Lacuna:** nenhum gesto foi feito na bancada.
""")

md("""
### Etapa 7 — shakedown (09–10/11) e gravação do ensaio (11/11) · **pendente**

Abra o registrador primeiro → reset no Mega → `# calibrado` → ≥ 20 s em normal → tecla **antes** do gesto → gesto → `x` depois do disparo. Depois de um `s`: `esteira: ligada` e `# rele A fechado` **antes** do reset.

```bash
sinais/.venv/bin/python -I sinais/registrador.py --serial <MEGA> --saida sinais/sessoes/shakedown --firmware arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino
sinais/.venv/bin/python -I sinais/registrador.py --serial <MEGA> --saida sinais/sessoes/ensaio-2026-11-11 --firmware arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino
sinais/.venv/bin/python -I sinais/avaliar.py sinais/sessoes/<pasta>/<AAAA-MM-DD-HHMM>
```

Shakedown: ≥ 1 episódio de cada falha. Ensaio: ≥ 3 por falha, reset entre eles. No painel, **não** pode aparecer a faixa SIMULADO. O `sinais.csv` de cada sessão pode ser analisado na seção 5 deste notebook. Revogue a chave do NodeMCU **depois da aula**.
""")

# ---------------------------------------------------------------- codigo
md("""
## 4. O código do gêmeo Wokwi

Projeto salvo (público, conta do operador): **[%s](%s)**, "VOCAID DEEP M7 - esteira (gemeo da bancada)".

As quatro células abaixo gravam os arquivos de `wokwi-mega-esteira-ky/` byte a byte, lidos do repositório quando o notebook foi gerado. O `sketch.ino` é **idêntico** ao firmware da bancada (`arduino-mega-esteira-ky.ino`). A célula seguinte confere os sha256 contra os registrados em `evidencias/2026-11-09-wokwi-projeto-salvo.txt`.

Para montar o projeto do zero no wokwi.com: crie um projeto **Arduino Mega**, cole `sketch.ino` e `diagram.json`, crie `esteira.chip.json` e `esteira.chip.c` (menu ▾ → *New file…*), confira que a chave "relé A" está fechada e inicie. Clique no chip para injetar `atrito`, `microfone_tampado`, `aleta_solta` ou `ruido_sala`.
""" % (WOKWI_URL, WOKWI_URL))

code("import os\nos.makedirs('gemeo', exist_ok=True)\nos.makedirs('dados', exist_ok=True)")
for nome in GEMEO:
    writefile("gemeo/" + nome, ler("wokwi-mega-esteira-ky/" + nome))

code("""
import hashlib

# sha256 registrados em evidencias/2026-11-09-wokwi-projeto-salvo.txt (= arquivos do repositorio e do projeto salvo)
ESPERADO = %r

ok = True
for nome, h in ESPERADO.items():
    dados = open('gemeo/' + nome, 'rb').read()
    real = hashlib.sha256(dados).hexdigest()
    bate = real == h
    ok &= bate
    print(('OK   ' if bate else 'DIFERE ') + nome.ljust(18) + real)
    if not bate and hashlib.sha256(dados + b'\\n').hexdigest() == h:
        print('     (so falta o \\\\n final: o editor tirou a quebra de linha da celula)')
assert ok, 'algum arquivo do gemeo difere do repositorio'
print('gemeo conferido: 4/4 sha256 iguais aos do repositorio e do projeto Wokwi salvo')
""" % {n: esperado[n] for n in GEMEO})

# ---------------------------------------------------------------- analise
md("""
## 5. Análise executável: z-score e ALERTA com a regra do firmware

As células abaixo:

1. gravam três seriais de exemplo, lidas dos arquivos do repositório:
   - **gêmeo, serial completa:** co-simulação de host (o `sketch.ino` e o `esteira.chip.c` reais, compilados contra stubs; semente 1), cenário **atrito 60 na janela 40**. É o mesmo firmware e o mesmo modelo do Wokwi, rodado sem o navegador;
   - **gêmeo no wokwi.com (08/11):** trecho copiado do monitor serial (`evidencias/2026-11-08-t15-wokwi-esteira.txt`; as janelas de calibração não estão todas lá, então a análise usa a linha `# calibrado:` impressa);
   - **bancada, etapa 1 (09/11):** serial real do Mega sem motor (`evidencias/2026-11-09-bancada-etapa-1.txt`);
2. convertem a serial no formato do `sinais.csv` do registrador (`t_s, epoca, janela_mega, rpm, som_rms, som_pico, vib, score_mega, estado_mega`);
3. recalculam calibração, z, score, streak e estado com a regra do firmware e comparam com as colunas `score` e `estado` que o Mega imprimiu.

Regra (constantes de `sketch.ino`): `JANELAS_AQUECE = 3`, `JANELAS_CALIB = 30`, `PISO = {rpm 60, som 3, vib 2}`, `LIMIAR_Z = 3,0` (estrito), `JANELAS_PARA_ALERTA = 2`, travado até o reset; SUSPEITA se a média de rpm da calibração < 60.

Para analisar uma sessão sua, troque `CSV_SESSAO` mais abaixo pelo `sinais.csv` de `sinais/sessoes/<pasta>/` (no Colab, envie o arquivo pelo painel de arquivos ou com `google.colab.files.upload()`).
""")

writefile("dados/gemeo-cosim-atrito.txt", serial_cosim)
writefile("dados/wokwi-2026-11-08-trecho.txt", ev_wokwi_t15)
writefile("dados/bancada-2026-11-09-etapa-1.txt", ev_etapa1)

code(r'''
import csv, math, re

# ---- regra do firmware (sketch.ino) ----
JANELAS_AQUECE = 3
JANELAS_CALIB = 30
JANELAS_PARA_ALERTA = 2
LIMIAR_Z = 3.0          # estrito: score == 3,0 nao conta
DESVIO_MIN = 1e-3       # so guarda de divisao
CANAIS = ('rpm', 'som_rms', 'vib')
PISO = {'rpm': 60.0, 'som_rms': 3.0, 'vib': 2.0}
ESTADOS = ('AQUECENDO', 'CALIBRANDO', 'NORMAL', 'ALERTA', 'SUSPEITA')
CAB_SINAIS = ('t_s', 'epoca', 'janela_mega', 'rpm', 'som_rms', 'som_pico', 'vib', 'score_mega', 'estado_mega')

RE_EPOCH = re.compile(r'^(\d{9,}\.\d+)\s+(.*)$')       # evidencias da bancada: "1794225276.0 <linha do Mega>"
RE_COMENTARIO = re.compile(r'\s{2,}\(.*\)\s*$')          # notas "(...)" coladas a direita no trecho do Wokwi


def ler_serial(texto):
    """Serial do Mega -> (janelas, eventos). Aceita a linha crua, com epoch na frente ou com nota entre parenteses."""
    janelas, eventos = [], []
    for bruta in texto.splitlines():
        s, t = bruta.strip(), None
        m = RE_EPOCH.match(s)
        if m:
            t, s = float(m.group(1)), m.group(2).strip()
        s = RE_COMENTARIO.sub('', s)
        if s.startswith('#'):
            eventos.append((t, s))
            continue
        c = [x.strip() for x in s.split(',')]
        if len(c) != 7 or c[6] not in ESTADOS or not c[0].isdigit():
            continue
        janelas.append({'t': t, 'janela_mega': int(c[0]), 'rpm': float(c[1]), 'som_rms': float(c[2]),
                        'som_pico': float(c[3]), 'vib': float(c[4]), 'score_mega': float(c[5]), 'estado_mega': c[6]})
    return janelas, eventos


def gravar_sinais_csv(janelas, caminho):
    """Mesmo cabecalho do sinais.csv do registrador. Sem epoch, t_s = janela (1 s por janela, tempo simulado)."""
    t0 = next((j['t'] for j in janelas if j['t'] is not None), None)
    epoca, anterior = 1, None
    with open(caminho, 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(CAB_SINAIS)
        for j in janelas:
            if anterior is not None and j['janela_mega'] <= anterior:
                epoca += 1                                   # janela nao cresceu = reset da placa
            anterior = j['janela_mega']
            t = (j['t'] - t0) if t0 is not None else float(j['janela_mega'])
            w.writerow(['%.1f' % t, epoca, j['janela_mega'], *(('%g' % j[k]) for k in
                        ('rpm', 'som_rms', 'som_pico', 'vib', 'score_mega')), j['estado_mega']])


def ler_sinais_csv(caminho):
    with open(caminho, newline='') as f:
        linhas = list(csv.DictReader(f))
    num = lambda v: float(v) if v not in (None, '') else None
    return [{'t_s': num(r['t_s']), 'epoca': int(r['epoca']), 'janela_mega': int(r['janela_mega']),
             **{k: num(r[k]) for k in ('rpm', 'som_rms', 'som_pico', 'vib', 'score_mega')},
             'estado_mega': r['estado_mega']} for r in linhas]


def calibracao_impressa(eventos):
    """'# calibrado: c0 media=.. desvio=.. c1 ..' -> {canal: (media, desvio)} (valores ja com piso)."""
    for _, e in eventos:
        if e.startswith('# calibrado:'):
            pares = re.findall(r'c(\d) media=([-\d.]+) desvio=([-\d.]+)', e)
            return {CANAIS[int(i)]: (float(m), float(d)) for i, m, d in pares}
    return None
''')

code(r'''
def avaliar(janelas, calib=None):
    """Recalcula o estado de uma epoca com a regra do firmware.
    calib=None: calibra com as janelas 4..33 do proprio CSV (media e desvio amostral, como o Welford do Mega).
    Devolve (linhas com z/score/estado recalculados, calibracao usada, avisos)."""
    avisos = []
    jan = sorted(janelas, key=lambda j: j['janela_mega'])
    if calib is None:
        cal = [j for j in jan if JANELAS_AQUECE < j['janela_mega'] <= JANELAS_AQUECE + JANELAS_CALIB]
        if len(cal) != JANELAS_CALIB:
            avisos.append('lacuna: %d de %d janelas de calibracao no CSV; a calibracao difere da do Mega'
                          % (len(cal), JANELAS_CALIB))
        calib = {}
        for c in CANAIS:
            xs = [j[c] for j in cal if j[c] is not None]
            n = len(xs)
            media = sum(xs) / n if n else 0.0
            desvio = math.sqrt(sum((x - media) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
            calib[c] = (media, max(desvio, PISO[c]))
    suspeita = calib['rpm'][0] < PISO['rpm']
    streak, travado, saida, anterior = 0, False, [], None
    for j in jan:
        n = j['janela_mega']
        r = dict(j, score=0.0, estado=None, **{'z_' + c: None for c in CANAIS})
        if n <= JANELAS_AQUECE:
            r['estado'] = 'AQUECENDO'
        elif n <= JANELAS_AQUECE + JANELAS_CALIB:
            r['estado'] = 'CALIBRANDO'
        elif suspeita:
            r['estado'] = 'SUSPEITA'
        else:
            if anterior is not None and n != anterior + 1:
                avisos.append('lacuna: faltam as janelas %d a %d no CSV; o streak pode diferir do Mega'
                              % (anterior + 1, n - 1))
            zs = []
            for c in CANAIS:
                if j[c] is None:                             # celula vazia no sinais.csv (campo ilegivel na serial)
                    avisos.append('lacuna: %s vazio na janela %d; score sem esse canal' % (c, n))
                    continue
                media, desvio = calib[c]
                z = (j[c] - media) / max(desvio, DESVIO_MIN)
                r['z_' + c] = z
                zs.append(abs(z))
            r['score'] = max(zs) if zs else 0.0
            streak = streak + 1 if r['score'] > LIMIAR_Z else 0
            travado = travado or streak >= JANELAS_PARA_ALERTA
            r['estado'] = 'ALERTA' if travado else 'NORMAL'
            anterior = n
        saida.append(r)
    return saida, calib, avisos


def conferir(saida, tol_score=0.15):
    """Compara o recalculado com o que o Mega imprimiu. score: tolerancia pelo arredondamento do CSV (0,1)."""
    dif = [r for r in saida if r['estado'] != r['estado_mega']
           or (r['score_mega'] is not None and abs(r['score'] - r['score_mega']) > tol_score)]
    disparo = next((r['janela_mega'] for r in saida if r['estado'] == 'ALERTA'), None)
    disparo_mega = next((r['janela_mega'] for r in saida if r['estado_mega'] == 'ALERTA'), None)
    print('janelas: %d | divergencias (estado ou |score| > %.2f): %d' % (len(saida), tol_score, len(dif)))
    print('primeiro ALERTA: recalculado %s | Mega %s' % (disparo, disparo_mega))
    for r in dif[:10]:
        print('  janela %d: recalculado %.2f %s | Mega %.1f %s'
              % (r['janela_mega'], r['score'], r['estado'], r['score_mega'], r['estado_mega']))
    return not dif


def tabela(saida, de, ate):
    print('jan    rpm som_rms    vib |   z_rpm   z_som   z_vib | score  estado     | Mega: score estado')
    for r in saida:
        if de <= r['janela_mega'] <= ate:
            z = ['%7.2f' % r['z_' + c] if r['z_' + c] is not None else '      -' for c in CANAIS]
            v = ['%6s' % ('-' if r[k] is None else '%.1f' % r[k]) for k in ('rpm', 'som_rms', 'vib', 'score_mega')]
            print('%3d %s %s %s | %s | %5.2f  %-10s | %s %s' % (
                r['janela_mega'], v[0], v[1], v[2], ' '.join(z), r['score'], r['estado'], v[3], r['estado_mega']))
''')

md("""
### 5a. Gêmeo, serial completa (co-simulação, atrito 60 na janela 40)

Serial → `dados/sinais-gemeo-atrito.csv` (formato do registrador) → leitura do CSV → recálculo. Esta é a célula a reaproveitar com uma sessão real: troque `CSV_SESSAO`.
""")

code(r'''
janelas, eventos = ler_serial(open('dados/gemeo-cosim-atrito.txt').read())
gravar_sinais_csv(janelas, 'dados/sinais-gemeo-atrito.csv')

CSV_SESSAO = 'dados/sinais-gemeo-atrito.csv'   # troque por sinais/sessoes/<pasta>/sinais.csv de uma sessao sua

sessao = ler_sinais_csv(CSV_SESSAO)
epocas = sorted({r['epoca'] for r in sessao})
print('%s: %d janelas, epocas %s' % (CSV_SESSAO, len(sessao), epocas))
resultados = {}
for ep in epocas:
    saida, calib, avisos = avaliar([r for r in sessao if r['epoca'] == ep])
    resultados[ep] = saida
    print('\n== epoca %d ==' % ep)
    print('calibracao recalculada: ' + ' | '.join('%s media=%.1f desvio=%.2f' % (c, *calib[c]) for c in CANAIS))
    for a in sorted(set(avisos)):
        print(a)
    conferir(saida)

print('\ncalibracao impressa pelo Mega:', calibracao_impressa(eventos))
saida_gemeo = resultados[epocas[0]]
tabela(saida_gemeo, 32, 46)
''')

code(r'''
# confere a calibracao recalculada com a linha '# calibrado:' do Mega e trava o resultado esperado do gemeo
_, calib, _ = avaliar([r for r in sessao if r['epoca'] == 1])
impressa = calibracao_impressa(eventos)
for c in CANAIS:
    assert abs(calib[c][0] - impressa[c][0]) <= 0.05 and abs(calib[c][1] - impressa[c][1]) <= 0.05, c
assert conferir(saida_gemeo)
assert next(r['janela_mega'] for r in saida_gemeo if r['estado'] == 'ALERTA') == 41
print('OK: calibracao, score e estado recalculados batem com o Mega; ALERTA travado na janela 41')
''')

code(r'''
import matplotlib.pyplot as plt

def grafico(saida, titulo):
    x = [r['janela_mega'] for r in saida]
    fig, ax = plt.subplots(4, 1, figsize=(10, 8), sharex=True)
    for a, c in zip(ax, CANAIS):
        a.plot(x, [r[c] for r in saida], marker='.', lw=1)
        a.set_ylabel(c)
    ax[3].plot(x, [r['score'] for r in saida], marker='.', lw=1, label='score recalculado')
    ax[3].plot(x, [r['score_mega'] for r in saida], ls='--', lw=1, label='score do Mega')
    ax[3].axhline(LIMIAR_Z, color='red', lw=0.8, label='limiar 3,0')
    ax[3].set_ylabel('score'); ax[3].set_xlabel('janela'); ax[3].legend(loc='upper left')
    disparo = next((r['janela_mega'] for r in saida if r['estado'] == 'ALERTA'), None)
    for a in ax:
        a.axvspan(0.5, JANELAS_AQUECE + JANELAS_CALIB + 0.5, color='grey', alpha=0.12)
        if disparo:
            a.axvline(disparo, color='red', ls=':', lw=1)
    ax[0].set_title(titulo + ' (cinza = aquecimento + calibracao; pontilhado = ALERTA)')
    plt.tight_layout(); plt.show()

grafico(saida_gemeo, 'Gemeo M7, co-simulacao, atrito 60 na janela 40')
''')

md("""
### 5b. Gêmeo no wokwi.com (08/11): trecho do monitor serial

O trecho não tem as 30 janelas de calibração, então o recálculo usa a calibração impressa (`# calibrado:`). Como ela sai arredondada (média com 1 casa), a tolerância do score é 0,15.
""")

code(r'''
janelas_w, eventos_w = ler_serial(open('dados/wokwi-2026-11-08-trecho.txt').read())
calib_w = calibracao_impressa(eventos_w)
print('calibracao impressa no Wokwi:', calib_w)
saida_w, _, avisos_w = avaliar(janelas_w, calib=calib_w)
for a in sorted(set(avisos_w)):
    print(a)
assert conferir(saida_w)
tabela(saida_w, 86, 96)
''')

md("""
### 5c. Bancada, etapa 1 (09/11): Mega real, sem motor

Sem motor, o rpm médio da calibração é 0 (< 60): a regra manda **SUSPEITA**, não ALERTA. A célula também mede, na própria serial, o tempo entre o cabeçalho CSV e a `# SUSPEITA` (o momento em que o relé B abre na etapa 2).
""")

code(r'''
for nome in ('bancada-2026-11-09-etapa-1.txt',):
    texto = open('dados/' + nome).read()
    jb, eb = ler_serial(texto)
    gravar_sinais_csv(jb, 'dados/sinais-etapa-1.csv')
    saida_b, calib_b, avisos_b = avaliar([r for r in ler_sinais_csv('dados/sinais-etapa-1.csv') if r['epoca'] == 1])
    print(nome, '| calibracao recalculada:', {c: (round(m, 1), round(d, 2)) for c, (m, d) in calib_b.items()})
    print('calibracao impressa pelo Mega:', calibracao_impressa(eb))
    assert conferir(saida_b)
    t_cab = next(float(l.split()[0]) for l in texto.splitlines() if l.endswith('janela,rpm,som_rms,som_pico,vib,score,estado'))
    t_susp = next(t for t, e in eb if e.startswith('# SUSPEITA'))
    print('cabecalho CSV -> # SUSPEITA: %.1f s (relogio do Mac)' % (t_susp - t_cab))
    print('estados recalculados:', sorted({r['estado'] for r in saida_b}))
''')

md("""
## 6. Lacunas abertas (09/11/2026)

- **Sensores reais:** rpm, som_rms e vib da bancada com o AK280 girando não foram medidos (falta o KY-010; o motor ainda não entrou). Os números do gêmeo (rpm ~2000, som ~55, vib ~6) são **alvos do modelo**, não medidas.
- **Relé A / NodeMCU:** não rodou no hardware nem contra a API com chave real.
- **Gestos `a m p s r`:** nenhum foi feito na bancada; não se sabe ainda se o cotonete dispara o ALERTA no AK280 real.
- **Falso alarme de vibração:** na varredura de 100 sementes do gêmeo, 1 teve um ALERTA falso (Poisson a 3 eventos/s). Se a mola real se comportar assim, a bancada terá o mesmo falso alarme raro.
- **Projeto Wokwi salvo:** os arquivos foram conferidos por sha256, mas a simulação ainda não foi rodada nesse projeto salvo (rodou em 08/11 num projeto anônimo com os mesmos arquivos).
- **Etapa 5b:** a barreira de laser não foi testada.
""")

nb = new_notebook(cells=celulas, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
    "language_info": {"name": "python"},
    "colab": {"provenance": [], "name": "m7-esteira-plano-e-testes.ipynb"},
})
nbformat.validate(nb)
os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
with open(SAIDA, "w", encoding="utf-8") as f:
    nbformat.write(nb, f)
print("escrito:", os.path.relpath(SAIDA, RAIZ), "| celulas:", len(celulas))
print("sha256 do gemeo conferidos com o repositorio:", ", ".join(GEMEO))
sys.exit(0)
