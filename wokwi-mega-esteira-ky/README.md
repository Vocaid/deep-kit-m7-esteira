# M7 no Mega, versão Wokwi (esteira = chip customizado)

Gêmeo no navegador do `arduino-mega-esteira-ky/` (bancada). É o protótipo de simulador do módulo e vem **antes** da montagem física. O firmware é **o mesmo, byte a byte**: `sketch.ino` é cópia exata de `../arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino` (o Wokwi exige o nome `sketch.ino`). A regra do gêmeo é zero linhas diferentes, e `sh verificar_gemeo.sh` falha se houver um byte diferente.

O Wokwi não tem o KY-010 nem o motor com volante. Um **chip customizado** (`esteira.chip.c`, part type `chip-esteira`) faz o papel do AK280 com a aleta de papel, do KY-010 (óptico), do KY-037 (microfone) e do KY-002 (mola), e o motor para quando a alimentação é cortada.

**Estado em 2026-11-08: verificado na co-simulação de host** (o `sketch.ino` real + o `esteira.chip.c` real contra stubs, ver abaixo), compilado para o Mega com o `arduino-cli` e **rodado no wokwi.com** (projeto anônimo, os quatro arquivos sem alteração): auto-teste 17/17, calibração com rpm 2002, som 55,0 e vib 5,7, e alerta travado 2 janelas depois de atrito 60, com o rpm caindo a 0 (`../evidencias/2026-11-08-t15-wokwi-esteira.txt`).

## Arquivos

| Arquivo | O que é |
|---|---|
| `sketch.ino` | cópia byte a byte do firmware da bancada |
| `verificar_gemeo.sh` | `cmp` entre os dois; falha se diferirem |
| `esteira.chip.json` | pinos e controles do chip (`chip-esteira`) |
| `esteira.chip.c` | modelo do motor, da aleta e dos três sensores (C, API de chips do Wokwi) |
| `diagram.json` | Mega, chave do relé A, relé B, chip, LEDs e buzzer |
| `teste-host/` | co-simulação de host (`rodar.sh`) e compilação para o Mega (`compilar_mega.sh`) |

## Circuito: o mesmo E físico da bancada

| Peça no Wokwi | Ligação | Na bancada |
|---|---|---|
| `wokwi-slide-switch` "app aprovou (relé A)" | 5 V do Mega → pino 2 (comum); pino 1 → COM do relé B | relé A do NodeMCU (`../esp8266-esteira-app/`) |
| `wokwi-relay-module` (relé B) | IN em D7, VCC no 5 V, GND no GND; **NO → PWR do chip**; NC solto | KY-019, contato COM/NO |
| chip `esteira` | VCC, GND, PWR (entrada com pulldown), OPT → D2, VIB → D3, SOM → A0 | AK280 + aleta + KY-010 + KY-037 + KY-002 |
| LED verde (OK) / LED vermelho (ALERTA) | D4 / D5, cada um com 220 Ω | iguais |
| `wokwi-buzzer` | D6 | buzzer ativo |

O motor só gira com PWR alto: chave fechada **E** relé B fechado, o mesmo caminho em série da bancada. Fios: vermelho = 5 V, preto = GND, laranja = 5 V depois da chave (o caminho de potência), amarelo = D7, verde = OPT/D2 e LED OK, roxo = VIB/D3, azul = SOM/A0.

## Como usar no wokwi.com

1. Crie um projeto **Arduino Mega**. Cole `sketch.ino` no `sketch.ino` do projeto.
2. Aba `diagram.json`: cole o `diagram.json` desta pasta.
3. Menu ▾ → *New file…* → `esteira.chip.json` (cole) e de novo → `esteira.chip.c` (cole). O Wokwi compila o chip ao iniciar.
4. Confira que a chave "relé A" está **fechada** (alavanca do lado do pino 1). Inicie a simulação (o servidor gratuito roda a uma fração do tempo real: as 33 janelas de aquecimento + calibração levam bem mais que 33 s de relógio).
5. Serial esperado: `AUTO-TESTE: 17/17 -> PASS`, o cabeçalho CSV, 3 janelas `AQUECENDO`, 30 `CALIBRANDO` e `# calibrado: c0 media=2000.0 ... c1 media=55... c2 media=5...`, depois `NORMAL` com score baixo.
6. Clique no chip durante a simulação para abrir os controles e injete uma falha (tabela abaixo). Depois do `# ALERTA TRAVADO` o relé B abre, o rpm cai a 0, o LED vermelho acende e o buzzer toca. Rearme = botão de reset do Mega (ou parar e iniciar), com a chave fechada.

Projetos anônimos não salvam: salve numa conta Wokwi antes da aula.

## Controles do chip

As letras são as teclas de rótulo do `../sinais/registrador.py`, para a aula usar o mesmo vocabulário da bancada.

| Controle | Faixa | Na bancada | O que o chip faz |
|---|---|---|---|
| `atrito` | 0–100 | cotonete no aro (`a`) | rpm alvo = 2000 · (1 − 0,35 · atrito/100); som com ruído áspero de até +40 % da amplitude; vibração +12 eventos/s · atrito/100 |
| `microfone_tampado` | 0–1 | fita no KY-037 (`m`) | toda a parte AC do som vezes 0,15; rpm e vibração intactos |
| `aleta_solta` | 0–1 | aleta descolando (`p`) | a aleta não bloqueia a fenda em voltas alternadas: o firmware lê ~metade do rpm, mas o motor real (som, vibração) não mudou. É a inconsistência entre canais |
| `ruido_sala` | 0–100 | barulho na sala (`r`) | rajadas (~150 ms ligado, ~350 ms desligado) de ruído de ruido_sala/100 · 120 contagens no som, independentes do motor; a mola não sente |
| chave "relé A" | aberta/fechada | parada pelo app (`s`) | PWR baixo: o motor desacelera (constante de tempo 0,8 s) até parar |

## Modelo do chip (`esteira.chip.c`)

Timer repetido de **250 µs**; xorshift32 de semente fixa (`SEMENTE_RNG 1`): a mesma simulação dá sempre o mesmo CSV.

- **Motor:** alvo 2000 · (1 − 0,35 · atrito/100) rpm com PWR alto, 0 com PWR baixo; 1ª ordem com constante de tempo 0,4 s subindo e 0,8 s descendo; tremida de ±1 % (quase gaussiana) sorteada a cada 50 ms.
- **OPT (KY-010, D2):** fase do eixo += rpm/60 · dt; LOW enquanto a aleta está na fenda (8 % da volta), HIGH no resto. Com `aleta_solta`, a volta ímpar não bloqueia. Abaixo de 30 rpm a aleta para onde estiver e o pino fica no nível atual (sem pulso falso).
- **SOM (KY-037, A0, `pin_dac_write`):** V = 2,5 V + (k · amplitude · 5/1024) · sinal, com sinal = tom em 2·rpm/60 Hz (o comutador) + 30 % de ruído branco; k = 0,15 com o microfone tampado. A amplitude vai de 11,5 contagens (parado: som_rms ~3) a 72,6 (som_rms ~55), linear até 1000 rpm e constante acima (o comutador já "canta" a meia rotação). Limitado a 0–5 V.
- **VIB (KY-002, D3):** eventos de Poisson a 3/s · rpm/2000 + 12/s · atrito/100, só com o motor girando; cada evento é o pino em LOW por ~1 ms e de volta a HIGH, ou seja 2 bordas CHANGE.

**API do Wokwi de que o chip depende** (`wokwi-api.h`, só chamadas documentadas): `pin_init` (PWR em `INPUT_PULLDOWN`, OPT/VIB em `OUTPUT`, SOM em `ANALOG`), `pin_read` (PWR), `pin_write` (OPT, VIB), `pin_dac_write` (SOM), `attr_init` + `attr_read` (os quatro controles, lidos a cada passo), `timer_init` + `timer_start` (o passo de 250 µs, repetido), `get_sim_nanos` (dt, rajadas da sala, duração do LOW da mola). Sem `libm` e sem `malloc`: o seno é uma aproximação polinomial e o estado é uma variável estática. Os pinos VCC e GND existem para a fiação, o chip não os lê.

## Calibração (alvos e o que a co-simulação mediu)

| Estado | rpm | som_rms | vib (bordas/s) | Medido na co-simulação (média de 30 janelas) |
|---|---|---|---|---|
| normal | ~2000 | ~55 | ~6 | rpm 2000,0 · som 55,1 · vib 5,3 (semente 1); média de 100 sementes: 1999,7 · 55,0 · 6,0 |
| atrito 60 | ~1580 | maior | ~20 | rpm 1580,0 · som 57,6 · vib 21,0 (atrito 60 desde o boot) |
| motor parado | 0 | ~3 | 0 | rpm 0 · som 3,1 · vib 0 |

O score tem de passar de 3 com folga em `a`, `m`, `p` e no corte de energia; a tabela de cenários abaixo mostra os valores.

## Co-simulação de host (`sh teste-host/rodar.sh`)

Substituto, **não é AVR nem o Wokwi**: compila o `sketch.ino` real (incluído) com o `esteira.chip.c` real (linkado) contra dois stubs, `Arduino.h` (micros, millis, analogRead, digitalRead, digitalWrite, pinMode, attachInterrupt em CHANGE, Serial no stdout, noInterrupts/interrupts, sqrt) e `wokwi-api.h` (as chamadas da lista acima). Um relógio virtual de 50 µs roda os timers do chip e o `loop()`: os `pin_write` do chip chegam ao `digitalRead`/`analogRead` e disparam as ISRs; o D7 do firmware fecha o relé B, e PWR = chave E relé B. O chip também compila sozinho com `clang -Wall -Wextra -Werror`. A falha entra logo depois da linha da janela 39 (vale a partir da janela 40). Resultado em 2026-11-08, semente 1:

| Cenário | Primeiro ALERTA (score) | Antes (janelas 34–39) rpm / som / vib | Na falha, até o disparo |
|---|---|---|---|
| normal | nenhum; 34–60 NORMAL, score máx. 2,6 | 2000 / 54,7 / 7,0 | — |
| atrito 60 na janela 40 | 41 (6,7) | 2000 / 54,7 / 7,0 | 1740 / 57,8 / 18,0; rpm 0 na janela 60 |
| microfone tampado na 40 | 41 (15,8) | 2000 / 54,7 / 7,0 | 2010 / 7,7 / 7,0 |
| aleta solta na 40 | 41 (16,3) | 2000 / 54,7 / 7,0 | 1020 / 53,8 / 7,0 |
| chave aberta na 40 (`s`) | 41 (28,3) | 2000 / 54,7 / 7,0 | 720 / 37,4 / 2,0 |
| chave aberta desde o boot | nenhum; `# SUSPEITA` na janela 33 | 0 / 3,1 / 0 | — |
| ruído da sala 100 na 40 | 41 (9,4) | 2000 / 54,7 / 7,0 | 2010 / 82,8 / 7,0 |

O ruído da sala dispara o ALERTA: é o resultado honesto da estatística (o som sai de ~55 para ~83, z ≈ 9), não um defeito do gêmeo. Bom gancho para a aula: um canal sozinho não distingue falha da máquina de barulho na sala; o rpm e a vibração ficaram parados.

**Cuidado, vibração de Poisson:** a 3 eventos/s, uma janela isolada passa de score 3 de vez em quando (até 9 eventos num segundo). Em 100 sementes, 22 tiveram ao menos uma janela NORMAL com score ≥ 3 nas janelas 34–60, e 1 chegou a um ALERTA falso (duas seguidas). As falhas dispararam em todas as 100 (janela 41, ou 42 em 7 % do atrito). A semente 1 (a primeira da varredura) passa. Se a mola real se comportar assim, a bancada terá o mesmo falso alarme raro: é do método (Poisson a 3 eventos/s, desvio calibrado ~3,4 bordas, cauda longa), não do simulador. Para varrer outra semente no host: compile o chip com `-DSEMENTE_RNG=n`.

Compilar para o Mega: `sh teste-host/compilar_mega.sh` (`--warnings all`; 11 054 B de flash, 653 B de RAM, igual à bancada). O `arduino-cli compile wokwi-mega-esteira-ky` direto **não funciona** nesta pasta: o arduino-cli exige o arquivo principal com o nome da pasta, e compilaria o `esteira.chip.c` para o AVR. O script copia só o `sketch.ino` para uma pasta temporária com o nome certo.

## O que é diferente da bancada

- **Sensores e motor são um modelo**, não física: números escolhidos para bater com a calibração acima. A bancada ainda não mediu os seus (o M7 não rodou no hardware), então os alvos do chip são estimativas.
- **O relé A é uma chave**, não o NodeMCU com o app; o Wokwi não tem ESP8266.
- **Alimentação do motor:** no Wokwi o PWR do chip vem do 5 V do Mega pelo contato do relé. Na bancada o contato chaveia o adaptador externo de 9–12 V e o motor **nunca** sai do 5 V do Mega.
- **Ruído elétrico das escovas, diodo e capacitor** não existem aqui; o KY-010 não tem salto de contato (a guarda de 200 µs não é exercitada).
- **Uma aleta, sempre limpa:** a fenda vê exatamente 8 % da volta; na bancada a largura da aleta e a polaridade do módulo variam.
- **Tempo:** o Wokwi gratuito roda abaixo do tempo real; o firmware conta o tempo simulado, então o CSV é o mesmo, só mais lento.
