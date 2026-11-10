# M7 / Task 13 — NodeMCU ESP8266: o app do Vocaid liga a esteira (relé A)

O NodeMCU consulta o Vocaid Connect por HTTPS, lê o campo `meta` de um artigo de pesquisa e fecha o **relé A** só enquanto o `meta` disser que a esteira está aprovada. Um commit feito no app (ou pelo Claude Code via MCP) liga o motor. O **relé B** (Mega, "a estatística não disparou") continua em série e pode cortar o motor mesmo com o app aprovando.

**Status:** compilado para `esp8266:esp8266:nodemcuv2` e lógica testada no host. **Não rodou no hardware** nem contra a API com chave real nesta sessão: o TLS com a CA fixada foi validado com `openssl verify` contra a cadeia real, mas o handshake do BearSSL no chip só se confirma na bancada.

## Convenção do marcador (o que o operador commita)

`contents.meta` é texto livre (`str | None` no schema). A regra vale para texto ou JSON:

| `meta` | Resultado |
|---|---|
| `esteira: ligada` (qualquer caixa, `=` ou espaço no lugar de `:`) | relé A fecha |
| `{"esteira":"ligada"}`, `{"esteira": "ligada", "x": 1}` | relé A fecha |
| `esteira: desligada`, vazio, `ligada` sem a palavra `esteira`, valor em outra linha, `esteira: ligada? nao`, `esteira: ligada -> desligada`, `esteira: ligada=false`, `esteira: ligada, depois desligada`, `esteira: ligada" mas nao`, `esteira: ligada} x`, `esteira: "ligada" talvez` | relé A abre |

**Nada pode vir depois de `ligada` na linha.** Em texto puro, só espaços até o fim do texto ou a quebra de linha (vírgula, aspas ou chave vetam). Se o valor abriu com aspas (`"ligada"`, JSON), depois de `ligada` tem de vir a aspa de fechamento e, depois dela, só espaços e então `,`, `}`, o fim do texto ou a quebra de linha. `esteira-ligada` (o `-` conta como separador) também vale. Regra a favor da segurança: **toda** ocorrência da palavra `esteira` no `meta` precisa ter o valor `ligada`; qualquer outra (inclusive `desligada`) veta. Por isso, não use a palavra "esteira" em outro lugar do `meta`. `desligada` nunca conta como `ligada` (a palavra tem de começar no valor).

## Ligação (série com o relé B)

```
adaptador externo 9–12 V (+) ──► RELÉ A (módulo no NodeMCU, COM/NO)
                                   ──► RELÉ B (KY-019 no Mega, COM/NO)
                                         ──► terminal + do AK280
adaptador (−) ───────────────────────────────► terminal − do AK280  ──► GND do Mega e do NodeMCU (GND em comum)
```

Os dois contatos em série: o motor só gira se o app aprovou **E** a estatística do Mega não disparou. Detalhes do motor, diodo 1N4007 e capacitor de 100 nF: `../arduino-mega-esteira-ky/README.md`.

| NodeMCU | Módulo do relé A |
|---|---|
| D1 (GPIO5) | IN |
| 3V3 ou VIN (5 V do USB), conforme o módulo | VCC |
| GND | GND |

O LED da placa (GPIO2) acende com o relé fechado. `RELE_ATIVO_BAIXO = true` no topo do `.ino` (padrão dos módulos comuns, igual aos sketches do Mega). O pino recebe o nível seguro (aberto) **antes** de virar saída, e `releA(bool)` é o único escritor.

### Verificação OBRIGATÓRIA de polaridade na bancada (motor DESCONECTADO)

Polaridade errada fecha o relé quando o sketch manda abrir. Antes de ligar o motor:

1. Deixe o motor e o adaptador fora do circuito. Com o multímetro em continuidade, ponta em COM e outra em NO do relé A.
2. Grave com um SSID **errado** em `segredos.h`: o sketch fica em `# rele A aberto: wi-fi fora`. COM–NO tem de estar **ABERTO** (sem continuidade).
3. Segure **RESET** (o GPIO5 fica flutuando durante o reset): COM–NO continua **ABERTO**.
4. Durante a partida (antes da primeira consulta) COM–NO está **ABERTO**.
5. Se em qualquer um desses estados houver continuidade, inverta `RELE_ATIVO_BAIXO`, regrave e repita tudo. **Se falhar nas duas polaridades, ou o relé nunca clicar, o módulo não é acionável pelos 3,3 V do GPIO:** use o NPN do parágrafo abaixo (2N2222/BC547, base com 1 kΩ, pull-down de 10 kΩ) e grave com `RELE_ATIVO_BAIXO = false`.
6. **Passo positivo, ainda com o motor desconectado:** grave o `segredos.h` real, faça um commit com `esteira: ligada` no `meta`: em até 10 s, `# rele A fechado` e COM–NO com **continuidade**. Commit com `esteira: desligada`: COM–NO **ABERTO** de novo.
7. Faça também a checagem do relé B (`../arduino-mega-esteira-ky/README.md`, "Checagens de bancada"). Só ligue o motor depois das duas.

**Atenção: GPIO de 3,3 V pode não acionar todo módulo de relé de 5 V** (o transistor ou o optoacoplador pedem mais tensão). Se o relé não clicar, ou clicar de forma instável, use um transistor NPN com as peças do operador: D1 → resistor de **1 kΩ** → base de um **2N2222 ou BC547**, mais um resistor de **10 kΩ da base ao emissor** (pull-down: o GPIO5 fica em alta impedância durante o reset e a base não pode flutuar); emissor no GND; coletor no IN do módulo se o módulo for ativo em baixo e tiver pull-up interno, **ou** no negativo da bobina de um relé nu (com diodo 1N4007 em antiparalelo na bobina, cátodo no +). Nesse arranjo a lógica inverte (o transistor inverte o sentido do pino): `RELE_ATIVO_BAIXO = false` e repita a verificação de polaridade acima, sem motor.

## Tabela de falhas (todas deixam o relé A ABERTO)

| Situação | Mensagem na serial (`# rele A aberto: …`) |
|---|---|
| Wi-Fi fora (agido no mesmo instante, sem esperar a consulta) | `wi-fi fora` |
| NTP não acertou o relógio (sem hora, o TLS não valida) | `ntp falhou` |
| DNS não resolveu (timeout de 3 s) | `dns falhou` |
| TLS ou rede falhou (certificado, handshake, timeout) | `tls/rede falhou (erro ssl N)` |
| HTTP diferente de 200 (401/403 chave ruim, 429 cota, 5xx…) | `http N` |
| JSON inválido ou truncado | `json invalido` |
| `contents.meta` ausente ou nulo | `meta ausente` |
| `meta` sem `esteira: ligada` | `meta sem 'esteira: ligada'` |
| Última resposta OK há mais de 3 intervalos | `resposta velha` |
| Uma consulta travada deixaria a resposta velha antes de terminar (o relé abre ANTES de consultar) | `consulta pode demorar mais que a validade` |
| Auto-teste do boot falhou | `auto-teste falhou, travado` |
| Boot, antes da primeira consulta | `aguardando primeira consulta` |

A mensagem é ASCII (sem acento). A chave e a senha do Wi-Fi nunca são impressas; os únicos dados do servidor na serial são o início do `fingerprint` (id do commit, 8 caracteres) quando muda e, uma vez, a memória livre (`# heap livre: …`) depois da primeira consulta TLS.

## Segurança do TLS

- **`setInsecure()` não é usado.** O sketch fixa a CA raiz com `BearSSL::X509List` (`certificados.h`) e valida a cadeia, incluindo a data (por isso o NTP vem antes do TLS).
- Cadeia de certificados: capture a do seu host com `openssl s_client -connect SEU_HOST_VOCAID:443 -showcerts` e confira se as raízes batem com `certificados.h` (Let's Encrypt).
- Âncoras embutidas (PEM baixado do site oficial letsencrypt.org/certs; ambas verificam a cadeia real com `openssl verify`):
  - **ISRG Root X1**, expira **04/06/2035**.
  - **ISRG Root YR**, expira **02/09/2045** (cobre o dia em que a Let's Encrypt parar de enviar o cruzamento por X1).
- Host: o do seu ambiente Vocaid, na constante `HOST` do `.ino` (sem `https://`). Sem chave, a API responde HTTP 401.

## Orçamento de consultas (cota PROFESSIONAL: 1000/dia, da organização inteira, 60/min)

`MODO_AULA 1`: a cada **10 s** nos primeiros **20 min** depois do boot (120 consultas), depois a cada **180 s**.

- 24 h ligado com um boot: 120 + (86 400 − 1 200) / 180 ≈ 120 + 473 = **~593/dia**, sobram ~407 para o resto da organização.
- **Cada reset ou queda de energia reinicia a janela de 10 s** (+120). Evite reiniciar à toa; 4 boots no mesmo dia já levam a ~1 070 e estouram a cota. Fora da aula, deixe desligado ou use `MODO_AULA 0` (480/dia).
- Pico de 6/min, bem abaixo do limite de 60/min. ENTERPRISE não tem esse teto prático.
- Resposta 429 vira `http 429` e abre o relé.
- **Proteção contra laço de reinício:** o sketch guarda um contador na memória RTC (sobrevive a WDT e exceção). Só contam as quedas do firmware (`REASON_WDT_RST`, `REASON_EXCEPTION_RST`, `REASON_SOFT_WDT_RST`): com 3 seguidas, ele **desliga o modo aula**, espera 60 s antes da primeira consulta, usa 180 s e imprime o motivo. O botão RESET, a regravação pelo USB e a energização **não contam** e zeram a sequência; o contador também zera depois de 10 min de funcionamento saudável.

## Latência (nota honesta)

Em modo aula o motor reage ao commit em **até 10 s** mais a duração da consulta (1–3 s com TLS). Depois dos 20 min, até **180 s**. Durante uma consulta o sketch fica bloqueado: DNS 3 s e conexão/TLS, cabeçalho e corpo com 4 s cada, no pior caso cerca de **15 s**, e o relé mantém o estado anterior nesse intervalo. Por isso, antes de cada consulta, se a resposta ficaria velha (mais de 3 intervalos) antes de 15 s de espera, o relé **abre primeiro**; em modo aula (limite de 30 s) isso acontece quando o último OK tem mais de 15 s. O corte pelo relé B (estatística do Mega) independe disso: está em série e não passa pelo app.

## Passos do operador

1. No app do Vocaid, crie uma chave de API com escopo **`research:read` somente**. Não use uma chave com `research:write` no dispositivo. A organização precisa estar em PROFESSIONAL ou ENTERPRISE.
2. Pegue o id do workspace do artigo: `rs_open_workspace` no MCP Connect, ou pelo app.
3. `cp segredos.exemplo.h segredos.h` e preencha Wi-Fi, chave e workspace. **`segredos.h` está no `.gitignore` (`**/segredos.h`, e `build/` também, porque `arduino-cli compile -e` gera um `.bin` com a chave): nunca commite.** O Wi-Fi tem de ser 2,4 GHz. Se o local bloquear UDP 123 (NTP), o relógio não acerta e o relé fica aberto (`ntp falhou`): use o **hotspot do celular** como alternativa.
   - **A chave fica na flash e pode ser lida na bancada com o esptool.** Use uma chave **dedicada** ao dispositivo e **revogue-a logo depois do ensaio/da aula**.
   - **Nunca ative o nível de debug `HTTP_CLIENT` do core** (Ferramentas → Debug level): ele imprime o cabeçalho `Authorization` na serial.
4. Para o lado do commit (P9): usar uma chave com `research:write` **no Claude Code, não no dispositivo**.
5. Compilar e gravar, na raiz do repositório:

```bash
arduino-cli config add board_manager.additional_urls https://arduino.esp8266.com/stable/package_esp8266com_index.json
arduino-cli core update-index && arduino-cli core install esp8266:esp8266
arduino-cli lib install ArduinoJson
arduino-cli compile --fqbn esp8266:esp8266:nodemcuv2 --warnings all esp8266-esteira-app
arduino-cli upload  --fqbn esp8266:esp8266:nodemcuv2 -p <PORTA> esp8266-esteira-app
```

Medido em 2026-11-08 (fix final; ESP8266 core 3.1.2, ArduinoJson 7.4.3, GCC do core): 383 076 B de código em flash (36 %) e 30 668 B de RAM global (38 %), **zero avisos** com `--warnings all`. As mensagens de biblioteca e do core, se aparecerem em outra versão, não são do nosso código.

## A demonstração

Antes: as duas checagens de relé (A acima e B no README do Mega) com o motor desconectado.

1. Ligue o NodeMCU: a serial mostra `AUTO-TESTE: 43/43 -> PASS`, `# rele A aberto: aguardando primeira consulta` e, logo em seguida, `# rele A aberto: wi-fi fora` (o Wi-Fi ainda está conectando). A primeira consulta real sai uns 10 s depois do boot. Com o `meta` atual sem marcador, o relé fica aberto.
2. No Claude Code (MCP Connect) ou no app: commit com `esteira: ligada` no campo `meta` do artigo. Em até 10 s a serial mostra `# commit novo no head: …` e `# rele A fechado: meta diz esteira ligada`; o relé A clica.
3. Dê reset no Mega: depois do AUTO-TESTE e do cabeçalho CSV, o relé B fecha e o motor parte.
4. Espere o `# calibrado:` no Mega (3 + 30 janelas, uns 33 s, com o motor girando limpo).
5. Falha por atrito no aro do volante (cotonete ou borracha num cabo): duas janelas acima de 3 → `ALERTA`, o relé B abre e o motor para mesmo com o app em `ligada`.

Parada pelo app (`esteira: desligada`), queda do Wi-Fi ou um `http 429` abrem o relé A: o motor para, e duas janelas depois o Mega trava em `ALERTA` (a queda de rpm é desvio). Rearme = reset do Mega com o relé A fechado, mais uns 33 s de recalibração.

## Teste de host (substituto, não é ESP8266)

`sh teste-host/rodar.sh` compila `logica.h` com vetores derivados da regra (marcador em texto e JSON, caixa, `desligada`, outra linha, texto depois de `ligada` em texto puro e depois da aspa de fechamento, aspa sem fechar, veto por ocorrência conflitante, vazio e nulo; idade exatamente 3 intervalos, 3 intervalos + 1 ms, sem estouro de 32 bits) e imprime `AUTO-TESTE: 43/43 -> PASS`. O sketch roda os mesmos vetores na partida e só libera o relé depois de passar. O HTTPS, o JSON em fluxo e o relé só se exercitam no hardware.
