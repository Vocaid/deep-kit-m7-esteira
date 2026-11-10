#!/bin/sh
# Co-simulacao de HOST (NAO e AVR, NAO e o Wokwi): compila o sketch.ino REAL (incluido) + o esteira.chip.c REAL (linkado)
# contra os stubs Arduino.h e wokwi-api.h e roda os 7 cenarios. Cada cenario imprime o CSV e as linhas "# CONFERE".
# Uso: sh teste-host/rodar.sh [cenario ...]   (sem argumento: todos)
set -e
cd "$(dirname "$0")"
OUT="${TMPDIR:-/tmp}/gemeo-m7-cosim"
mkdir -p "$OUT"

sh ../verificar_gemeo.sh

# o chip sozinho, com os avisos ligados (o mesmo arquivo que o wokwi.com compila)
clang -std=c11 -Wall -Wextra -Werror -I. -c ../esteira.chip.c -o "$OUT/esteira.chip.o"
clang -std=c11 -Wall -Wextra -Werror -I. -c wokwi_stub.c -o "$OUT/wokwi_stub.o"
clang++ -std=c++17 -Wall -Wextra -I. -c cosim.cpp -o "$OUT/cosim.o"
clang++ "$OUT/cosim.o" "$OUT/esteira.chip.o" "$OUT/wokwi_stub.o" -o "$OUT/cosim"

CENARIOS="${*:-normal atrito microfone aleta chave chave_boot ruido}"
falhas=0
for c in $CENARIOS; do
  if "$OUT/cosim" "$c" > "$OUT/$c.txt"; then r=ok; else r=FALHOU; falhas=$((falhas + 1)); fi
  cat "$OUT/$c.txt"
  echo
done
echo "== resumo (saidas completas em $OUT) =="
for c in $CENARIOS; do grep -h -e "^# calibrado:" -e "^# RESUMO" -e "FALHOU" "$OUT/$c.txt" || true; done
[ "$falhas" -eq 0 ] && echo "co-simulacao: todos os cenarios conferidos" || { echo "co-simulacao: $falhas cenario(s) FALHARAM"; exit 1; }
