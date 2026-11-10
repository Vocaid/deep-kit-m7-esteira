// VOCAID DEEP - gemeo Wokwi do M7: chip customizado "esteira" (part type chip-esteira).
// Simula, num so chip, o que a bancada tem em volta do Mega: o motor AK280 com a aleta de papel no volante, o KY-010
// (optico, OPT -> D2), o KY-037 (microfone, SOM -> A0) e o KY-002 (mola de vibracao, VIB -> D3). O motor so gira com
// PWR alto, e PWR vem do NO do rele B (KY-019, D7) passando pela chave do rele A ("app aprovou"): o mesmo E em serie.
//
// API do Wokwi usada (wokwi-api.h, so chamadas documentadas): pin_init, pin_read, pin_write, pin_dac_write,
// attr_init, attr_read, timer_init, timer_start, get_sim_nanos. Sem libm: o seno e uma aproximacao polinomial.
// Tudo e deterministico: um timer repetido de 250 us e um xorshift32 de semente fixa.
//
// Controles (esteira.chip.json, clique no chip durante a simulacao). A letra e a tecla de rotulo do sinais/registrador.py:
//   atrito 0-100 (a) | microfone_tampado 0-1 (m) | aleta_solta 0-1 (p) | ruido_sala 0-100 (r)
#include "wokwi-api.h"
#include <stdbool.h>
#include <stdint.h>

#define TICK_US 250u                      // passo do modelo: timer repetido de 250 us
#ifndef SEMENTE_RNG
#define SEMENTE_RNG 1u                    // semente fixa do xorshift32 (o teste de host pode trocar com -DSEMENTE_RNG=n)
#endif

// ---------- motor (AK280 + volante) ----------
#define RPM_NOMINAL 2000.0f               // rpm com PWR alto e atrito 0
#define ATRITO_QUEDA 0.35f                // alvo = 2000 * (1 - 0,35 * atrito/100): atrito 60 -> 1580 rpm
#define TAU_SUBIDA_S 0.4f                 // constante de tempo de 1a ordem acelerando
#define TAU_DESCIDA_S 0.8f                // ... e desacelerando (o volante de latao segura)
#define JITTER_PERIODO_NS 50000000ull     // tremida de rpm sorteada a cada 50 ms
#define JITTER_MAX 0.01f                  // +-1 %, forma quase gaussiana (soma de 3 uniformes / 3)
#define RPM_PARADO 30.0f                  // abaixo disso a aleta para onde estiver: OPT congela no nivel atual

// ---------- KY-010 (optico) ----------
#define FRACAO_ALETA 0.08f                // a aleta ocupa 8 % da volta: OPT em LOW enquanto ela esta na fenda

// ---------- KY-037 (som) ----------
// V = 2,5 V + (k * amplitude_counts * 5/1024) * sinal, sinal = tom em 2*rpm/60 Hz (comutador) + 30 % de ruido branco.
// rms do sinal com ruido de variancia 1: sqrt(0,5 + 0,3^2) = 0,768 -> amplitude 71,6 da som_rms ~55 a 2000 rpm;
// parado, so o ruido conta: 0,3 * 10 = som_rms ~3 (nivel de quantizacao).
#define AMP_GIRANDO 72.6f                 // amplitude (contagens do ADC) com o motor em regime
#define AMP_PARADO 11.5f                  // amplitude com o motor parado
#define RPM_SOM_PLENO 1000.0f             // a amplitude sobe linear de 0 a 1000 rpm e satura (o comutador ja "canta")
#define RUIDO_BRANCO 0.30f
#define ATRITO_ASPERO_MAX 0.40f           // atrito 100 soma ruido aspero de +40 % da amplitude
#define FATOR_TAMPADO 0.15f               // microfone tampado: toda a parte AC vezes 0,15
#define SALA_PERIODO_NS 500000000ull      // ruido da sala em rajadas: 150 ms ligado, 350 ms desligado
#define SALA_LIGADO_NS 150000000ull
#define SALA_AMP_MAX 120.0f               // ruido_sala 100 -> ruido de 120 contagens, independente do motor

// ---------- KY-002 (vibracao) ----------
#define VIB_TAXA_GIRANDO 3.0f             // eventos/s a 2000 rpm (6 bordas/s), proporcional ao rpm
#define VIB_TAXA_ATRITO 12.0f             // + 12 eventos/s * atrito/100 (so com o motor girando)
#define VIB_LOW_NS 1000000ull             // cada evento: LOW por ~1 ms e volta a HIGH = 2 bordas CHANGE

typedef struct {
  pin_t pwr, opt, vib, som;
  uint32_t a_atrito, a_tampado, a_solta, a_sala;
  uint64_t t_ant_ns, t_jitter_ns, t_vib_alto_ns;
  float rpm, jitter, fase;                // fase do eixo em voltas, mantida em [0, 2): a volta par e a impar
  uint32_t nivel_opt, nivel_vib;
  uint32_t rng;
} esteira_t;

static esteira_t g_esteira;

// xorshift32, semente fixa: a mesma simulacao sempre da o mesmo CSV
static uint32_t sorteio(esteira_t *e) {
  uint32_t x = e->rng;
  x ^= x << 13; x ^= x >> 17; x ^= x << 5;
  e->rng = x;
  return x;
}
static float uniforme(esteira_t *e) { return (float)(sorteio(e) >> 8) * (1.0f / 16777216.0f); }   // [0, 1)
static float simetrico(esteira_t *e) { return 2.0f * uniforme(e) - 1.0f; }                         // [-1, 1)
static float quase_gauss(esteira_t *e) { return simetrico(e) + simetrico(e) + simetrico(e); }       // variancia 1, limitado a +-3

// seno de 2*pi*c para c em voltas, sem libm: parabola refinada (erro < 0,1 %)
static float seno_voltas(float c) {
  c -= (float)(int)c;
  if (c < 0.0f) c += 1.0f;
  float x = c < 0.5f ? 2.0f * c : 2.0f * c - 2.0f;   // x em [-1, 1): sen(pi*x)
  float ax = x < 0.0f ? -x : x;
  float y = 4.0f * x * (1.0f - ax);
  float ay = y < 0.0f ? -y : y;
  return 0.225f * (y * ay - y) + y;
}

static void escreve_digital(pin_t pino, uint32_t *atual, uint32_t novo) {
  if (*atual == novo) return;
  *atual = novo;
  pin_write(pino, novo);
}

static void passo(void *dados) {
  esteira_t *e = (esteira_t *)dados;
  uint64_t agora = get_sim_nanos();
  float dt = (float)(agora - e->t_ant_ns) * 1e-9f;
  e->t_ant_ns = agora;

  float atrito = (float)attr_read(e->a_atrito);
  if (atrito > 100.0f) atrito = 100.0f;
  bool tampado = attr_read(e->a_tampado) != 0;
  bool solta = attr_read(e->a_solta) != 0;
  float sala = (float)attr_read(e->a_sala);
  if (sala > 100.0f) sala = 100.0f;

  // ---- motor: 1a ordem rumo ao alvo; PWR baixo = alvo 0 (o motor so gira com os dois reles fechados) ----
  float alvo = pin_read(e->pwr) ? RPM_NOMINAL * (1.0f - ATRITO_QUEDA * atrito / 100.0f) : 0.0f;
  float tau = alvo > e->rpm ? TAU_SUBIDA_S : TAU_DESCIDA_S;
  e->rpm += (alvo - e->rpm) * (dt / tau);
  if (e->rpm < 0.0f) e->rpm = 0.0f;
  if (agora - e->t_jitter_ns >= JITTER_PERIODO_NS) {
    e->t_jitter_ns = agora;
    e->jitter = JITTER_MAX * quase_gauss(e) / 3.0f;
  }
  float rpm = e->rpm * (1.0f + e->jitter);
  bool girando = rpm >= RPM_PARADO;

  // ---- KY-010: LOW enquanto a aleta esta na fenda; aleta solta nao bloqueia na volta impar ----
  if (girando) {                                         // parado: a aleta fica onde esta e OPT nao muda (sem pulso falso)
    e->fase += rpm / 60.0f * dt;
    while (e->fase >= 2.0f) e->fase -= 2.0f;
    uint32_t volta_impar = e->fase >= 1.0f;
    float frac = e->fase - (float)volta_impar;
    bool bloqueia = frac < FRACAO_ALETA && !(solta && volta_impar);
    escreve_digital(e->opt, &e->nivel_opt, bloqueia ? LOW : HIGH);
  }

  // ---- KY-037: tom do comutador (2 por volta) + ruido branco + aspero do atrito + rajadas da sala ----
  float fator = rpm >= RPM_SOM_PLENO ? 1.0f : rpm / RPM_SOM_PLENO;
  float amp = AMP_PARADO + (AMP_GIRANDO - AMP_PARADO) * fator;
  float sinal = seno_voltas(2.0f * e->fase) + RUIDO_BRANCO * quase_gauss(e);
  if (girando) sinal += ATRITO_ASPERO_MAX * (atrito / 100.0f) * quase_gauss(e);
  float ac = amp * sinal;
  if ((agora % SALA_PERIODO_NS) < SALA_LIGADO_NS) ac += SALA_AMP_MAX * (sala / 100.0f) * quase_gauss(e);
  float k = tampado ? FATOR_TAMPADO : 1.0f;
  float v = 2.5f + k * ac * (5.0f / 1024.0f);
  if (v < 0.0f) v = 0.0f;
  if (v > 5.0f) v = 5.0f;
  pin_dac_write(e->som, v);

  // ---- KY-002: eventos de Poisson (sorteio por passo), cada um LOW ~1 ms; a sala nao mexe na mola ----
  if (e->nivel_vib == LOW) {
    if (agora >= e->t_vib_alto_ns) escreve_digital(e->vib, &e->nivel_vib, HIGH);
  } else if (girando) {
    float taxa = VIB_TAXA_GIRANDO * (rpm / RPM_NOMINAL) + VIB_TAXA_ATRITO * (atrito / 100.0f);
    if (uniforme(e) < taxa * dt) {
      escreve_digital(e->vib, &e->nivel_vib, LOW);
      e->t_vib_alto_ns = agora + VIB_LOW_NS;
    }
  }
}

void chip_init(void) {
  esteira_t *e = &g_esteira;
  e->pwr = pin_init("PWR", INPUT_PULLDOWN);
  e->opt = pin_init("OPT", OUTPUT);
  e->vib = pin_init("VIB", OUTPUT);
  e->som = pin_init("SOM", ANALOG);
  e->a_atrito = attr_init("atrito", 0);
  e->a_tampado = attr_init("microfone_tampado", 0);
  e->a_solta = attr_init("aleta_solta", 0);
  e->a_sala = attr_init("ruido_sala", 0);
  e->rpm = 0.0f; e->jitter = 0.0f;
  e->fase = 0.5f;                                       // aleta fora da fenda no boot: OPT comeca HIGH
  e->rng = SEMENTE_RNG;
  e->nivel_opt = HIGH; pin_write(e->opt, HIGH);
  e->nivel_vib = HIGH; pin_write(e->vib, HIGH);
  pin_dac_write(e->som, 2.5f);
  e->t_ant_ns = e->t_jitter_ns = get_sim_nanos();
  e->t_vib_alto_ns = 0;

  const timer_config_t cfg = { .user_data = e, .callback = passo };
  timer_t t = timer_init(&cfg);
  timer_start(t, TICK_US, true);
}
