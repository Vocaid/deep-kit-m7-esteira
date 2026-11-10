# Painel de replay (offline)

Arquivo único: `index.html` (CSS e JS inline, sem CDN, sem fontes web, sem pedido externo).
Só lê `manifesto.json`, `sinais.csv`, `detectores.jsonl` (obrigatórios) e `rotulos.csv`, `eventos.csv`, `avaliacao.json` (opcionais) de uma pasta de sessão. Não roda nenhum modelo: usa `classe_final` e `por_que` já gravados por `sinais/avaliar.py`.

## Abrir
- Botão "Carregar sessão": escolha a pasta da sessão (funciona também por `file://`).
- Ou, num servidor local: `cd sinais && python -I -m http.server 8130 --bind 127.0.0.1` e abra
  `http://127.0.0.1:8130/painel/index.html?sessao=../sessoes/<id>`.
- `?aula=1` recusa sessão simulada (e qualquer sessão cujo manifesto não diga `"simulado": false`).

## Teclado
espaço = tocar/pausar · ← → = passo de 1 janela · T = tabela por evento · Esc = fecha a tabela.
