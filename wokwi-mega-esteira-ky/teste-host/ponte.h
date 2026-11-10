// Ponte entre o lado "Wokwi" (wokwi_stub.c + esteira.chip.c, em C) e o lado "Mega" (cosim.cpp + sketch.ino, em C++).
// Nao inclui wokwi-api.h de proposito: LOW/HIGH/INPUT do Wokwi colidiriam com as macros do Arduino.h.
#ifndef PONTE_H
#define PONTE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void wk_iniciar(void);                               // chama o chip_init() do chip
void wk_avancar_ate(uint64_t ns);                    // roda os timers do chip vencidos ate o instante ns
uint32_t wk_nivel(const char *pino);                 // ultimo pin_write do chip naquele pino
float wk_tensao(const char *pino);                   // ultimo pin_dac_write do chip naquele pino
void wk_entrada(const char *pino, uint32_t nivel);   // nivel que o circuito aplica num pino de entrada do chip
void wk_attr(const char *nome, uint32_t valor);      // mexe num controle (o slider do Wokwi)

void ponte_pino_mudou(const char *pino, uint32_t nivel);   // implementada no lado Mega: dispara a ISR em CHANGE

#ifdef __cplusplus
}
#endif

#endif
