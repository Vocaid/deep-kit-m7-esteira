# M7 — esteira orquestrada no Arduino Mega (kit KY)

Esteira que se autoexcita e se vigia: três sensores (óptico, som, vibração) viram um escore de saúde calibrado, e o relé corta o motor quando o escore passa do limite.

**Método, sem exagero:** estatística calibrada (z-score por canal, escore = maior |z|). Não é rede neural; o upgrade seria um MLP int8 como no módulo de impacto. A serial imprime essa linha na partida.

**Status:** módulo só de bancada, **testado no host** (lógica pura + AUTO-TESTE) e compilado para o Mega. Não rodou no hardware nesta sessão. O Wokwi não tem peça KY-010; o gêmeo no simulador usa um chip customizado no lugar do motor e dos sensores: `../wokwi-mega-esteira-ky/` (rodou no wokwi.com em 08/11, `../evidencias/2026-11-08-t15-wokwi-esteira.txt`).

## Mapa de pinos (fixo)

| Peça | Pino do Mega | Observação |
|---|---|---|
| KY-010 (óptico), saída S | D2 (INT4) | duas guardas em µs: 2000 µs entre bordas contadas (até 500 Hz) e 200 µs desde qualquer borda; 1 aleta = 1 pulso por volta |
| KY-037 (som), saída analógica AO | A0 | amostrada a cada ~1 ms |
| KY-002 (vibração), saída S | D3 (INT5) | conta TODAS as bordas, sem debounce |
| KY-019 (relé B), S | D7 | `motorEnergizado(bool)`, `RELE_ATIVO_BAIXO = false` (o S do KY-019 aciona um NPN: ativo em ALTO; confirme na checagem do relé B) |
| LED verde (OK) | D4 | resistor de 220 ohm |
| LED vermelho (ALERTA) | D5 | resistor de 220 ohm |
| Buzzer ativo | D6 | |
| ULN2003 IN1–IN4 (28BYJ-48) | D8–D11 | só com `-DMOTOR_PASSO=1`; meio passo, ~2 ms/passo, sem bloquear |
| KY-028 (termistor), AO | A1 | desligado: `#define CANAL_TEMP 0`; com `1` vira o 4º canal |

Cada módulo KY: `-` no GND, o pino do meio (ou `+`) em 5 V, `S`/`AO` no pino da tabela. Confira a serigrafia de cada placa.

## Montagem: quem é a esteira (padrão: Akiyama AK280 + volante de latão)

`MOTOR_PASSO 0` (padrão) compila fora todo o código do motor de passo. O motor do processo é o **Akiyama AK280** (etiqueta `18.3PV12S4600S`: 12 V, ~4600 rpm em vazio) com o **volante de latão** no eixo, ligado **somente** pelo contato do relé KY-019 (`motorEnergizado()`, único escritor do pino D7). No ALERTA o relé abre e o motor para.

**Por que o AK280 e não o 28BYJ-48:** a ~15 rpm o 28BYJ-48 dá ao KY-010 um pulso a cada 4 s (0 a 1 contagem por janela de 1 s): o canal óptico fica cego. O AK280 a 5–9 V gira a ~2000 rpm, ou seja ~33 pulsos por janela com **uma aleta**, tem o som forte de comutador (KY-037) e uma falha honesta e segura: atrito ao vivo no aro do volante (cotonete ou borracha num cabo) derruba o rpm e muda o som e a vibração (KY-002).

- **Aleta (regra):** uma tira de papel de **5–15 mm ao longo do aro**, nunca cobrindo mais da metade do aro, colada no volante e passando pela fenda do KY-010 sem raspar. `PULSOS_POR_VOLTA = 1`. O código funciona com qualquer polaridade do módulo desde que o arco coberto e o arco livre durem cada um > 200 µs na rotação máxima.
- **Checagem de polaridade no ensaio:** com o motor parado, bloqueie a fenda com a mão (papel) e observe o LED do KY-010 e a serial. O código funciona nos dois casos (conta a borda LOW, com guarda de 200 µs desde qualquer borda); só anote qual polaridade apareceu (LOW = aleta presente ou ausente).
- **Cadeia de alimentação (E físico em série):**

```
adaptador externo 9–12 V (+) ──► RELÉ A (NodeMCU, "aprovado no app"; ver ../esp8266-esteira-app/README.md)
                                   ──► RELÉ B (KY-019 no Mega, "a estatística não disparou"; COM/NO)
                                         ──► terminal + do AK280
adaptador (−) ───────────────────────────────► terminal − do AK280  ──► GND do Mega (GND em comum)
```

  O motor só gira se o app aprovou **E** a estatística do Mega não disparou. Os dois contatos estão em série, então qualquer um que abra corta o motor, sem depender de software no caminho de potência.
- **Proteção do motor (peças do operador):** **diodo 1N4007 em antiparalelo nos terminais do motor, cátodo (faixa) no +**, e **capacitor cerâmico de 100 nF direto nos terminais**. O diodo absorve o pico de abertura do relé; o capacitor reduz o ruído das escovas, que senão entra no KY-037 e nas interrupções.
- **Lado da bobina do relé B:** `+`/`-`/`S` do KY-019 no 5 V, GND e D7 do Mega (só a bobina, corrente baixa). Use os terminais **COM e NO** do contato, nunca NC.
- **Tensão do motor:** parta com 5–6 V (o adaptador no menor valor, ou o motor reserva), rode normalmente em 9 V, máximo 12 V. O teste do motor em baixa tensão vem **depois** das duas checagens de relé abaixo.
- **Relé A:** é o módulo do NodeMCU (`../esp8266-esteira-app/`), que só fecha com `esteira: ligada` no artigo do app. Sem ele no circuito, só o relé B (estatística do Mega) protege o motor.
- **Motor reserva:** motor DC de lata chata de 3–6 V (classe 130/180), alimentado **pelo mesmo adaptador externo, na menor tensão** (nunca pelo 5 V do Mega nem pelo trilho da protoboard: a mesma regra da corrente de partida vale para ele), passando pelos mesmos relés A e B, com o mesmo diodo e capacitor. Gira bem mais rápido: recalibre o rpm esperado e confira se a contagem por janela não passa de ~200.
- **Motor de passo (opcional, `-DMOTOR_PASSO=1`):** o 28BYJ-48 via ULN2003 em D8–D11 continua compilando, como alvo lento para a demo de visão (rpm por câmera). Aí o `PULSOS_POR_VOLTA` e a aleta voltam a render só 0–1 pulso por janela e o canal óptico é cego: não use essa configuração como esteira do M7.

## Checagens de bancada OBRIGATÓRIAS (motor DESCONECTADO)

Polaridade errada fecha o relé quando o sketch manda abrir. Antes de ligar o motor, faça as duas:

1. **Relé A (NodeMCU):** a verificação de `../esp8266-esteira-app/README.md` (aberto sem Wi-Fi, no RESET e na partida; fechado com `ligada`, aberto com `desligada`).
2. **Relé B (KY-019 no Mega):** motor e adaptador fora do circuito, multímetro em continuidade entre **COM e NO** do KY-019.
   - Segure RESET do Mega e solte: durante o boot e o AUTO-TESTE, COM–NO **ABERTO**.
   - Depois do cabeçalho `janela,rpm,som_rms,som_pico,vib,score,estado`: COM–NO **FECHADO** (o sketch liga o motor).
   - Uns 33 s depois, sem motor o rpm da calibração é 0 e a serial imprime `# SUSPEITA: motor cortado -- de reset com o motor girando`: COM–NO **ABERTO** de novo. O ALERTA usa o mesmo corte (`motorEnergizado(false)`).
   - Se algum estado sair invertido, troque `RELE_ATIVO_BAIXO`, regrave e repita. Use **NO, não NC**.
3. Só então ligue o motor ao contato e confira que o AK280 gira em baixa tensão (5–6 V) antes da demonstração.

## Ordem da demonstração (relé A e relé B)

1. Commit com `esteira: ligada` no `meta` do artigo (app ou Claude Code via Connect).
2. Espere `# rele A fechado: meta diz esteira ligada` na serial do NodeMCU.
3. Dê reset no Mega (o motor só gira agora: os dois relés fechados).
4. Espere o `# calibrado:` (3 janelas de aquecimento + 30 de calibração, com o motor girando limpo).
5. Falha por atrito (passo 2 da injeção de falha abaixo) → `ALERTA`.

Se o relé A abrir no meio (parada pelo app com `desligada`, queda do Wi-Fi ou um `http 429`), o motor para e o Mega vê a queda de rpm como falha: duas janelas depois trava em `ALERTA`. Rearme = reset do Mega com o relé A fechado, mais uns 33 s de recalibração.

## Alimentação (regra de ouro)

- **NUNCA** alimente o AK280 pelo pino 5 V do Mega nem pelo trilho da protoboard: a corrente de partida de um motor de 12 V derruba o trilho, reinicia o Mega e pode danificar o regulador. O motor sai do adaptador externo, sempre via relé A e relé B.
- **GND em comum**: Mega, adaptador (−), módulo do relé B e KY no mesmo GND. Sem isso as leituras e o relé ficam erráticos.
- Se o Mega reiniciar quando o motor parte, o problema é a alimentação (ou falta o capacitor de 100 nF), não o sketch.
- Sem rede elétrica na bancada: o relé comuta só a fonte de baixa tensão do motor.
- **Segurança mecânica e elétrica:** óculos de proteção; volante preso (grampo) e **coberto** (copo ou caixa de plástico transparente) porque a aleta de papel pode se soltar; sem mangas soltas nem cabelo solto; dedos longe do eixo; adaptador de **≥ 1 A**, de preferência com fusível ou limite de corrente; primeiro teste com o adaptador na menor tensão (ou o motor reserva de 5–6 V); prenda o motor e o suporte do KY-010 antes de ligar.

## Como funciona

0. **AQUECENDO** (3 janelas): descartadas, não entram na calibração (DC do KY-037 e partida do motor).
1. **CALIBRANDO** (30 janelas de 1 s): o motor gira, o sketch mede média e desvio de cada canal (rpm, som rms, bordas de vibração). LED verde pisca. O desvio nunca fica abaixo de um piso por canal (rpm 60/`PULSOS_POR_VOLTA`, um degrau de contagem; som_rms 3 contagens do ADC; vib 2 = um evento são 2 bordas; temperatura 3), para que uma esteira muito estável não gere disparo falso. Se o rpm médio da calibração for menor que um degrau (motor parado, por exemplo com o relé A aberto), a serial avisa `# SUSPEITA: motor cortado -- de reset com o motor girando`, o relé B abre e o estado fica `SUSPEITA`: o ALERTA não é avaliado até o reset.
2. **NORMAL**: a cada janela, `z = (x − média) / desvio` por canal, `score = max|z|`.
3. **ALERTA**: só depois de **2 janelas seguidas** com `score > 3,0` (um pico isolado não dispara; exatamente 3,0 não conta). Relé desliga o motor, esteira parada, buzzer, LED vermelho. **Travado: não há rearme automático.**

Saída CSV (115200): `janela,rpm,som_rms,som_pico,vib,score,estado`. Linhas com `#` são narração.

## Injeção de falha (demonstração)

Princípio: a calibração aprende o que for "normal" nas 30 janelas. A falha tem de entrar **depois** do `# calibrado:`, com o motor já girando.

1. Espere o `# calibrado:` e algumas linhas `NORMAL` com `score` baixo.
2. **Falha ao vivo (a usar no take, mais segura):** **ensaie uma vez com o cotonete real antes do take.** Critério: `score` > 3 em 2 janelas seguidas levando a `ALERTA`. Se não chegar: toque mais firme e, depois, suba a tensão um degrau. O rpm fica muito acima do piso de 60 rpm, então uma queda de algumas centenas de rpm dá z ≫ 3, mas isso não está verificado até o ensaio. Encoste de leve no aro do volante um **objeto macio seguro por um cabo** (borracha de apagar ou cotonete seco, sem dedos perto do eixo). O atrito derruba o rpm e muda o som e a vibração.
3. **Falha de desbalanceio (a mais fiel, fora do take):** fita adesiva + uma moeda no aro do volante, com o motor parado. Como a massa só entra com o motor parado, a calibração a absorveria como "normal": serve para uma rodada em que a massa fica colada de propósito e se mostra que o sistema, calibrado assim, não alerta. Para ver o ALERTA ao vivo, use o passo 2.
4. Na segunda janela seguida acima de 3, a serial imprime `# ALERTA TRAVADO`, o relé B clica e abre, o motor para, o buzzer toca e o LED vermelho acende. Retirar o objeto não desfaz: está travado.

## Rearme = reset

Só o botão RESET da placa (ou desligar e ligar o USB) rearma. A calibração recomeça do zero: 3 janelas de aquecimento + 30 de calibração, uns 33 s, com o relé A fechado. **A demonstração deve começar sem falha (nada tocando o volante)**: o que a placa vê nas 30 janelas de calibração vira o "normal".

## Compilar e gravar

Na raiz do repositório:

```bash
arduino-cli compile --fqbn arduino:avr:mega --warnings all arduino-mega-esteira-ky
arduino-cli upload  --fqbn arduino:avr:mega -p <PORTA> arduino-mega-esteira-ky
```

Medido em 2026-11-08 (fix final): padrão AK280 (`MOTOR_PASSO 0`) 11 054 B de flash (4 %) e 653 B de RAM global (7 %); com `--build-property "compiler.cpp.extra_flags=-DMOTOR_PASSO=1"` 11 328 B e 698 B; ambos sem avisos no nosso código (só 4 do core, `new.cpp`). O relé liga só depois de o AUTO-TESTE passar.

## Teste de host (substituto, não é AVR)

`sh teste-host/rodar.sh` compila o `.ino` real com stubs e roda o `setup()`: AUTO-TESTE de 17 vetores (aceitarPulso com as duas guardas, calma, cada canal dominando sozinho, um degrau de rpm sem disparo, pisos, calibração suspeita, pico isolado sem disparo, duas janelas disparam, limiar exato mantém o estado, trava). Registro em `../evidencias/2026-11-08-t12-host.txt`. O host tem `int` de 32 bits; a largura de `int` do AVR é coberta pela passada `--warnings all`. Os caminhos de ISR, ADC e relé só se exercitam no hardware.
