#!/bin/sh
# Compila o sketch.ino do gemeo para o Mega com o arduino-cli.
# `arduino-cli compile wokwi-mega-esteira-ky` direto nao funciona nesta pasta, por dois motivos do proprio arduino-cli:
#   1. ele exige o arquivo principal com o nome da pasta (wokwi-mega-esteira-ky.ino), e o Wokwi exige sketch.ino;
#   2. ele compila todo .c da raiz da pasta, e o esteira.chip.c (do Wokwi, inclui wokwi-api.h) quebraria o build do AVR.
# Por isso copia SO o sketch.ino para uma pasta temporaria com o nome certo e compila la.
set -e
cd "$(dirname "$0")/.."
sh verificar_gemeo.sh
DIR="${TMPDIR:-/tmp}/gemeo-m7-mega/wokwi-mega-esteira-ky"
rm -rf "$DIR" && mkdir -p "$DIR"
cp sketch.ino "$DIR/wokwi-mega-esteira-ky.ino"
cmp sketch.ino "$DIR/wokwi-mega-esteira-ky.ino"
arduino-cli compile --fqbn arduino:avr:mega --warnings all "$DIR"
