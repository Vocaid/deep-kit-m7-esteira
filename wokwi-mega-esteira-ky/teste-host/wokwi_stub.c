// Implementacao de HOST do wokwi-api.h (NAO e o Wokwi): pinos, controles e timers do chip num relogio virtual.
// O cosim.cpp avanca o relogio com wk_avancar_ate(); cada pin_write que muda o nivel avisa o lado Mega (ponte_pino_mudou).
#include "wokwi-api.h"
#include "ponte.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PINOS 8
#define MAX_ATTRS 8
#define MAX_TIMERS 4

typedef struct { const char *nome; uint32_t modo, nivel; float tensao; } pino_t;
typedef struct { const char *nome; uint32_t valor; } attr_t;
typedef struct { timer_config_t cfg; uint64_t periodo_ns, proximo_ns; bool ativo, repete; } timer_host_t;

static pino_t g_pinos[MAX_PINOS];
static int g_n_pinos = 0;
static attr_t g_attrs[MAX_ATTRS];
static int g_n_attrs = 0;
static timer_host_t g_timers[MAX_TIMERS];
static int g_n_timers = 0;
static uint64_t g_agora_ns = 0;

static void falhar(const char *msg, const char *nome) {
  fprintf(stderr, "wokwi_stub: %s (%s)\n", msg, nome ? nome : "-");
  exit(2);
}

static int achar_pino(const char *nome) {
  for (int i = 0; i < g_n_pinos; i++) if (strcmp(g_pinos[i].nome, nome) == 0) return i;
  return -1;
}

static int achar_attr(const char *nome) {
  for (int i = 0; i < g_n_attrs; i++) if (strcmp(g_attrs[i].nome, nome) == 0) return i;
  return -1;
}

// ---------- API do chip ----------
pin_t pin_init(const char *name, uint32_t mode) {
  int i = achar_pino(name);
  if (i < 0) {
    if (g_n_pinos == MAX_PINOS) falhar("pinos demais", name);
    i = g_n_pinos++;
    g_pinos[i].nome = name;
    g_pinos[i].nivel = LOW;
    g_pinos[i].tensao = 0.0f;
  }
  g_pinos[i].modo = mode;
  return (pin_t)i;
}

void pin_write(pin_t pin, uint32_t value) {
  if (pin < 0 || pin >= g_n_pinos) falhar("pin_write em pino invalido", NULL);
  pino_t *p = &g_pinos[pin];
  if (p->modo != OUTPUT) falhar("pin_write em pino que nao e OUTPUT", p->nome);
  uint32_t v = value ? HIGH : LOW;
  if (v == p->nivel) return;
  p->nivel = v;
  ponte_pino_mudou(p->nome, v);
}

uint32_t pin_read(pin_t pin) {
  if (pin < 0 || pin >= g_n_pinos) falhar("pin_read em pino invalido", NULL);
  return g_pinos[pin].nivel;
}

void pin_dac_write(pin_t pin, float voltage) {
  if (pin < 0 || pin >= g_n_pinos) falhar("pin_dac_write em pino invalido", NULL);
  if (g_pinos[pin].modo != ANALOG) falhar("pin_dac_write em pino que nao e ANALOG", g_pinos[pin].nome);
  g_pinos[pin].tensao = voltage;
}

uint32_t attr_init(const char *name, uint32_t default_value) {
  int i = achar_attr(name);
  if (i < 0) {
    if (g_n_attrs == MAX_ATTRS) falhar("controles demais", name);
    i = g_n_attrs++;
    g_attrs[i].nome = name;
    g_attrs[i].valor = default_value;
  }
  return (uint32_t)i;
}

uint32_t attr_read(uint32_t attr_id) {
  if (attr_id >= (uint32_t)g_n_attrs) falhar("attr_read com id invalido", NULL);
  return g_attrs[attr_id].valor;
}

timer_t timer_init(const timer_config_t *config) {
  if (g_n_timers == MAX_TIMERS) falhar("timers demais", NULL);
  g_timers[g_n_timers].cfg = *config;
  g_timers[g_n_timers].ativo = false;
  return (timer_t)g_n_timers++;
}

void timer_start(timer_t timer_id, uint32_t micros, bool repeat) {
  if (timer_id >= (timer_t)g_n_timers) falhar("timer_start com id invalido", NULL);
  timer_host_t *t = &g_timers[timer_id];
  t->periodo_ns = (uint64_t)micros * 1000u;
  t->proximo_ns = g_agora_ns + t->periodo_ns;
  t->repete = repeat;
  t->ativo = true;
}

uint64_t get_sim_nanos(void) { return g_agora_ns; }

// ---------- lado da co-simulacao ----------
void wk_iniciar(void) { chip_init(); }

void wk_avancar_ate(uint64_t ns) {
  for (;;) {
    int prox = -1;
    for (int i = 0; i < g_n_timers; i++)
      if (g_timers[i].ativo && g_timers[i].proximo_ns <= ns && (prox < 0 || g_timers[i].proximo_ns < g_timers[prox].proximo_ns)) prox = i;
    if (prox < 0) break;
    timer_host_t *t = &g_timers[prox];
    g_agora_ns = t->proximo_ns;
    if (t->repete) t->proximo_ns += t->periodo_ns; else t->ativo = false;
    t->cfg.callback(t->cfg.user_data);
  }
  g_agora_ns = ns;
}

uint32_t wk_nivel(const char *pino) {
  int i = achar_pino(pino);
  if (i < 0) falhar("wk_nivel: pino nao iniciado", pino);
  return g_pinos[i].nivel;
}

float wk_tensao(const char *pino) {
  int i = achar_pino(pino);
  if (i < 0) falhar("wk_tensao: pino nao iniciado", pino);
  return g_pinos[i].tensao;
}

void wk_entrada(const char *pino, uint32_t nivel) {
  int i = achar_pino(pino);
  if (i < 0) falhar("wk_entrada: pino nao iniciado", pino);
  if (g_pinos[i].modo == OUTPUT || g_pinos[i].modo == ANALOG) falhar("wk_entrada em pino de saida", pino);
  g_pinos[i].nivel = nivel ? HIGH : LOW;
}

void wk_attr(const char *nome, uint32_t valor) {
  int i = achar_attr(nome);
  if (i < 0) falhar("wk_attr: controle nao iniciado pelo chip", nome);
  g_attrs[i].valor = valor;
}
