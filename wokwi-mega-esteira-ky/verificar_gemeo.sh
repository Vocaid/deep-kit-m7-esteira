#!/bin/sh
# Regra do gemeo: o sketch.ino do Wokwi e o firmware da bancada sao o MESMO arquivo, zero linhas diferentes.
# Falha (saida 1) se houver qualquer byte diferente. Rode da raiz do repositorio ou de qualquer lugar.
cd "$(dirname "$0")"
if cmp ../arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino sketch.ino; then
  echo "gemeo OK: sketch.ino identico a arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino"
else
  echo "gemeo QUEBRADO: copie de novo  cp ../arduino-mega-esteira-ky/arduino-mega-esteira-ky.ino sketch.ino"
  exit 1
fi
