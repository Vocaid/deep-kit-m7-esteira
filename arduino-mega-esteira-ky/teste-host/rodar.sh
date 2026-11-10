#!/bin/sh
# Substituto de HOST (NAO e AVR, NAO e Wokwi): compila o sketch REAL (../arduino-mega-esteira-ky.ino, incluido, nao copiado)
# com stubs e roda o setup() (AUTO-TESTE). O host tem int de 32 bits: largura de int do AVR fica com
#   arduino-cli compile --fqbn arduino:avr:mega --warnings all arduino-mega-esteira-ky
set -e
cd "$(dirname "$0")"
c++ -Wall -Wextra -I. main_host.cpp -o /tmp/t12_host_bin
/tmp/t12_host_bin
