# VOCAID DEEP M7 · esteira instrumentada (kit aberto)

Kit de laboratório do módulo M7 do VOCAID DEEP: uma **esteira instrumentada** com **Arduino Mega** e sensores **KY-010** (óptico, rotação), **KY-037** (som) e **KY-002** (vibração), **relé** de proteção e **NodeMCU (ESP8266)** que lê o estado do workspace de pesquisa e comanda o relé.

- Abrir no Colab: [plano e testes](https://colab.research.google.com/github/Vocaid/deep-kit-m7-esteira/blob/main/colab/m7-esteira-plano-e-testes.ipynb)
- Gêmeo digital no Wokwi: https://wokwi.com/projects/480213362190861313

## Mapa de pastas

| Pasta | Conteúdo |
|---|---|
| `colab/` | notebook do plano e testes e o gerador (`gerar_notebook.py`) |
| `wokwi-mega-esteira-ky/` | gêmeo Wokwi: sketch, `diagram.json`, chip da esteira, testes no host |
| `arduino-mega-esteira-ky/` | firmware do Mega (diagnóstico + esteira) e `teste-host/` |
| `esp8266-esteira-app/` | firmware do NodeMCU; copie `segredos.exemplo.h` para `segredos.h` (ignorado pelo git) e preencha |
| `sinais/` | registrador, métricas, avaliação, simulador, painéis, notebook e testes |
| `guia/` | guia do curso (`index.html`) com fotos em `img/` |

## Como rodar

```bash
python3 -m venv sinais/.venv && sinais/.venv/bin/pip install -r sinais/requirements.txt
# Diagnóstico ao vivo (grave sinais/painel-ao-vivo/diag_ao_vivo/diag_ao_vivo.ino no Mega antes):
sinais/.venv/bin/python -I sinais/painel-ao-vivo/ponte.py --serial /dev/cu.usbmodemXXXX   # abre http://localhost:8000/
# Painel de sinais de uma sessão gravada:
python3 -m http.server 8130 --directory sinais   # http://127.0.0.1:8130/painel/index.html?sessao=<pasta>
# Testes:
sinais/.venv/bin/python -m pytest sinais/tests
```

Detalhes de cada parte nos README das pastas.

## Segurança

O motor **só** é alimentado por **fonte externa** e **através dos dois relés**. Nunca ligue o motor aos pinos do Arduino/NodeMCU nem pela USB. Use diodo e capacitor de proteção conforme o README do Mega.

## Licença

Código: Apache-2.0 · Textos e imagens: CC BY 4.0
