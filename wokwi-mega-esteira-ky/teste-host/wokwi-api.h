// Stub de HOST do wokwi-api.h (NAO e o Wokwi): as mesmas assinaturas do cabecalho oficial dos chips customizados,
// so o subconjunto que o esteira.chip.c usa. A implementacao fica em wokwi_stub.c (relogio virtual da co-simulacao).
#ifndef WOKWI_API_H
#define WOKWI_API_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef int32_t pin_t;
typedef uint32_t timer_t;

enum pin_value { LOW = 0, HIGH = 1 };
enum pin_mode { INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2, INPUT_PULLDOWN = 3, ANALOG = 4, OUTPUT_LOW = 16, OUTPUT_HIGH = 17 };

typedef struct {
  void *user_data;
  void (*callback)(void *user_data);
  uint32_t reserved[8];
} timer_config_t;

pin_t pin_init(const char *name, uint32_t mode);
void pin_write(pin_t pin, uint32_t value);
uint32_t pin_read(pin_t pin);
void pin_dac_write(pin_t pin, float voltage);

uint32_t attr_init(const char *name, uint32_t default_value);
uint32_t attr_read(uint32_t attr_id);

timer_t timer_init(const timer_config_t *config);
void timer_start(timer_t timer_id, uint32_t micros, bool repeat);

uint64_t get_sim_nanos(void);

void chip_init(void);   // ponto de entrada do chip (o Wokwi chama uma vez por instancia)

#ifdef __cplusplus
}
#endif

#endif
