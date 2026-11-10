#!/bin/sh
# Substituto de HOST (NAO e ESP8266): compila ../logica.h com os vetores derivados da regra e imprime AUTO-TESTE.
set -e
cd "$(dirname "$0")"
BIN=$(mktemp)
trap 'rm -f "$BIN"' EXIT
c++ -std=c++11 -Wall -Wextra -I. main_host.cpp -o "$BIN"
"$BIN"
