// Co-simulacao de HOST (NAO e AVR, NAO e o Wokwi): o sketch.ino REAL (incluido, nao copiado) roda contra o chip
// esteira.chip.c REAL (linkado) num relogio virtual de 50 us. Cada passo: roda os timers do chip vencidos (os pin_write
// dele chegam ao digitalRead/analogRead do firmware e disparam as ISRs em CHANGE) e depois um loop() do firmware.
// O D7 do firmware fecha o rele B; PWR do chip = chave do rele A (variavel do teste) E rele B, o mesmo E em serie da bancada.
//
// Uso: cosim <cenario>   (normal | atrito | microfone | aleta | chave | chave_boot | ruido)
// Imprime o CSV do firmware, confere o cenario (linhas "# CONFERE") e uma linha "# RESUMO". Saida 0 = tudo conferido.
#include "Arduino.h"
#include "ponte.h"
#include <stdlib.h>
#include <string.h>

// ---------- o "Mega" no host ----------
static uint64_t cs_t_us = 0;                 // relogio virtual (us)
static const uint64_t CS_PASSO_US = 50;
static int cs_entrada[70];                   // nivel visto pelo digitalRead (D2 = OPT, D3 = VIB)
static int cs_saida[70];                     // ultimo digitalWrite (D4 LED_OK, D5 LED_ALERTA, D6 buzzer, D7 rele B)
static void (*cs_isr[70])();                 // attachInterrupt(..., CHANGE)
static bool cs_chave = true;                 // rele A ("app aprovou"): a slide switch do diagram.json
static int cs_interrupcoes_desligadas = 0;

static void cs_atualiza_pwr() { wk_entrada("PWR", (cs_chave && cs_saida[7] == HIGH) ? 1u : 0u); }

static void cs_passo(bool rodar_loop);
static void cs_linha(const char *s);

unsigned long micros() { return (unsigned long)cs_t_us; }
unsigned long millis() { return (unsigned long)(cs_t_us / 1000u); }
void delay(unsigned long ms) { for (uint64_t i = 0; i < ms * 1000u / CS_PASSO_US; i++) cs_passo(false); }

int analogRead(int pino) {
  if (pino != A0) return 0;
  float v = wk_tensao("SOM");
  int n = (int)(v * 1024.0f / 5.0f);           // ADC do AVR: Vin * 1024 / Vref, truncado
  return n < 0 ? 0 : (n > 1023 ? 1023 : n);
}

int digitalRead(int pino) { return cs_entrada[pino]; }
void digitalWrite(int pino, int nivel) {
  cs_saida[pino] = nivel ? HIGH : LOW;
  if (pino == 7) cs_atualiza_pwr();
}
void pinMode(int, int) {}
// Os timers do chip so rodam entre dois loop() (nunca dentro de fimDeJanela), entao nenhuma borda chega com as
// interrupcoes desligadas. Contamos o aninhamento so para conferir que o firmware as religa.
void noInterrupts() { cs_interrupcoes_desligadas++; }
void interrupts() { cs_interrupcoes_desligadas--; }
void attachInterrupt(int interrupcao, void (*isr)(), int modo) {
  if (modo != CHANGE) { fprintf(stderr, "cosim: so CHANGE\n"); exit(2); }
  cs_isr[interrupcao] = isr;
}

extern "C" void ponte_pino_mudou(const char *pino, uint32_t nivel) {
  int p = strcmp(pino, "OPT") == 0 ? 2 : (strcmp(pino, "VIB") == 0 ? 3 : -1);
  if (p < 0) return;
  cs_entrada[p] = (int)nivel;
  if (cs_isr[p]) cs_isr[p]();
}

static char cs_buf[512];
static size_t cs_len = 0;
void cs_serial(const char *s) {
  fputs(s, stdout);
  for (; *s; s++) {
    if (*s == '\n') { cs_buf[cs_len] = 0; cs_linha(cs_buf); cs_len = 0; }
    else if (cs_len + 1 < sizeof cs_buf) cs_buf[cs_len++] = *s;
  }
}

// ---------- o firmware da bancada, sem mudar uma linha ----------
#include "../sketch.ino"

// ---------- cenarios ----------
struct Cenario {
  const char *nome;
  bool chave_no_boot;        // rele A fechado no boot
  const char *controle;      // controle do chip mexido antes da janela 40 (NULL = nenhum)
  uint32_t valor;
  bool abre_chave;           // abre o rele A antes da janela 40 (parada pelo app, tecla s)
};
static const Cenario CENARIOS[] = {
  {"normal", true, NULL, 0, false},
  {"atrito", true, "atrito", 60, false},
  {"microfone", true, "microfone_tampado", 1, false},
  {"aleta", true, "aleta_solta", 1, false},
  {"chave", true, NULL, 0, true},
  {"chave_boot", false, NULL, 0, false},
  {"ruido", true, "ruido_sala", 100, false},
};
static const Cenario *cs_cen = NULL;
static const int JANELA_FALHA = 40, JANELA_FIM = 60;

struct Janela { bool ok; long rpm; float som, score; long pico, vib; char estado[16]; };
static Janela cs_jan[JANELA_FIM + 2];
static int cs_ultima = 0, cs_janela_calib = 0, cs_janela_suspeita = 0, cs_janela_trip = 0;
static int cs_auto_certos = -1, cs_auto_total = -1;
static bool cs_auto_pass = false;

static void cs_linha(const char *s) {
  if (s[0] >= '0' && s[0] <= '9') {
    Janela j; int n;
    if (sscanf(s, "%d,%ld,%f,%ld,%ld,%f,%15s", &n, &j.rpm, &j.som, &j.pico, &j.vib, &j.score, j.estado) == 7 && n > 0 && n <= JANELA_FIM) {
      j.ok = true; cs_jan[n] = j; cs_ultima = n;
      if (n == JANELA_FALHA - 1 && cs_cen) {               // a falha vale a partir da janela 40
        if (cs_cen->controle) wk_attr(cs_cen->controle, cs_cen->valor);
        if (cs_cen->abre_chave) { cs_chave = false; cs_atualiza_pwr(); }
        printf("# [cosim] falha injetada: %s\n", cs_cen->controle ? cs_cen->controle : "chave do rele A aberta");
      }
    }
  } else if (strncmp(s, "AUTO-TESTE: ", 12) == 0) {
    sscanf(s + 12, "%d/%d", &cs_auto_certos, &cs_auto_total);
    cs_auto_pass = strstr(s, "-> PASS") != NULL;
  } else if (strncmp(s, "# calibrado:", 12) == 0) {
    cs_janela_calib = (int)g_janela;
  } else if (strncmp(s, "# SUSPEITA", 10) == 0) {
    cs_janela_suspeita = (int)g_janela;
  } else if (strncmp(s, "# ALERTA TRAVADO", 16) == 0) {
    cs_janela_trip = (int)g_janela;
  }
}

static void cs_passo(bool rodar_loop) {
  cs_t_us += CS_PASSO_US;
  wk_avancar_ate(cs_t_us * 1000u);
  if (rodar_loop) loop();
}

// ---------- conferencias ----------
static int cs_falhas = 0;
static void confere(bool ok, const char *o_que) {
  printf("# CONFERE %s: %s\n", ok ? "ok" : "FALHOU", o_que);
  if (!ok) cs_falhas++;
}
static float z(int canal, float x) { return (x - g_media[canal]) / g_desvio[canal]; }
static float media(int a, int b, int campo) {
  float s = 0; int n = 0;
  for (int i = a; i <= b; i++) {
    if (!cs_jan[i].ok) continue;
    s += campo == 0 ? (float)cs_jan[i].rpm : (campo == 1 ? cs_jan[i].som : (float)cs_jan[i].vib);
    n++;
  }
  return n ? s / n : 0.0f;
}
// Nas janelas a..b, |z| do canal fica abaixo de 3 (o canal "nao mudou")
static bool canal_calmo(int canal, int a, int b) {
  for (int i = a; i <= b; i++) {
    float x = canal == 0 ? (float)cs_jan[i].rpm : (canal == 1 ? cs_jan[i].som : (float)cs_jan[i].vib);
    if (!cs_jan[i].ok || fabsf(z(canal, x)) >= 3.0f) return false;
  }
  return true;
}

int main(int argc, char **argv) {
  setvbuf(stdout, NULL, _IOLBF, 0);
  if (argc < 2) { fprintf(stderr, "uso: cosim <cenario>\n"); return 2; }
  for (const Cenario &c : CENARIOS) if (strcmp(c.nome, argv[1]) == 0) cs_cen = &c;
  if (!cs_cen) { fprintf(stderr, "cenario desconhecido: %s\n", argv[1]); return 2; }
  printf("# [cosim] cenario %s\n", cs_cen->nome);

  cs_entrada[2] = cs_entrada[3] = HIGH;
  cs_chave = cs_cen->chave_no_boot;
  wk_iniciar();
  cs_atualiza_pwr();
  setup();
  while (cs_ultima < JANELA_FIM) {
    cs_passo(true);
    if (cs_t_us > 200000000ull) { printf("# [cosim] tempo esgotado na janela %d\n", cs_ultima); return 1; }
  }

  confere(cs_auto_pass && cs_auto_certos == 17 && cs_auto_total == 17, "AUTO-TESTE 17/17 PASS");
  confere(cs_janela_calib == 33, "# calibrado: na janela 33");
  confere(cs_interrupcoes_desligadas == 0, "noInterrupts()/interrupts() pareados");

  const char *n = cs_cen->nome;
  int t = cs_janela_trip;
  int fim_falha = t ? t : JANELA_FIM;                       // janelas com a falha e o motor ainda energizado
  if (!strcmp(n, "normal")) {
    bool todas = true;
    for (int i = 34; i <= JANELA_FIM; i++) todas = todas && cs_jan[i].ok && !strcmp(cs_jan[i].estado, "NORMAL") && cs_jan[i].score < 3.0f;
    confere(todas, "janelas 34-60 NORMAL com score < 3");
    confere(t == 0 && cs_saida[7] == HIGH, "sem ALERTA, rele B fechado");
  } else if (!strcmp(n, "atrito")) {
    confere(t >= JANELA_FALHA && t <= JANELA_FALHA + 2, "ALERTA em <= 3 janelas (40-42)");
    confere(cs_saida[7] == LOW && cs_saida[5] == HIGH && cs_saida[6] == HIGH, "travado: rele B aberto, LED vermelho e buzzer");
    confere(cs_jan[JANELA_FIM].rpm == 0, "rele B aberto -> PWR baixo -> rpm 0 na janela 60");
  } else if (!strcmp(n, "microfone")) {
    confere(t >= JANELA_FALHA, "ALERTA depois da falha");
    confere(t && canal_calmo(0, JANELA_FALHA, t) && canal_calmo(2, JANELA_FALHA, t), "rpm e vib sem mudar (|z| < 3) ate o disparo");
  } else if (!strcmp(n, "aleta")) {
    confere(t >= JANELA_FALHA, "ALERTA depois da falha");
    bool metade = t > 0;
    for (int i = JANELA_FALHA; t && i <= t; i++) metade = metade && fabsf((float)cs_jan[i].rpm / g_media[0] - 0.5f) <= 0.1f;
    confere(metade, "rpm lido ~ metade (0,4-0,6 da media) ate o disparo");
    confere(t && canal_calmo(1, JANELA_FALHA, t) && canal_calmo(2, JANELA_FALHA, t), "som e vib sem mudar (|z| < 3): o motor real e o mesmo");
  } else if (!strcmp(n, "chave")) {
    confere(t >= JANELA_FALHA && t <= JANELA_FALHA + 2, "ALERTA em <= 3 janelas (40-42)");
    confere(z(0, (float)cs_jan[JANELA_FALHA].rpm) < -3.0f, "rpm da janela 40 cai mais de 3 desvios");
    confere(cs_jan[JANELA_FIM].rpm == 0, "rpm 0 na janela 60");
  } else if (!strcmp(n, "chave_boot")) {
    confere(cs_janela_suspeita == 33, "# SUSPEITA logo apos a calibracao (janela 33)");
    bool todas = true;
    for (int i = 34; i <= JANELA_FIM; i++) todas = todas && cs_jan[i].ok && !strcmp(cs_jan[i].estado, "SUSPEITA");
    confere(todas && t == 0, "janelas 34-60 SUSPEITA, nunca ALERTA");
    confere(cs_saida[7] == LOW, "rele B aberto pela SUSPEITA");
  } else if (!strcmp(n, "ruido")) {
    confere(fabsf(z(1, media(JANELA_FALHA, fim_falha, 1))) > 3.0f, "som muda (|z| da media > 3)");
    confere(canal_calmo(0, JANELA_FALHA, fim_falha) && canal_calmo(2, JANELA_FALHA, fim_falha), "rpm e vib sem mudar (|z| < 3)");
  }

  printf("# RESUMO %s: ", n);
  if (t) printf("primeiro ALERTA na janela %d (score %.1f)", t, cs_jan[t].score); else printf("sem ALERTA");
  if (cs_janela_suspeita) printf(", SUSPEITA na janela %d", cs_janela_suspeita);
  printf(" | antes (34-39) rpm %.0f som %.1f vib %.1f", media(34, 39, 0), media(34, 39, 1), media(34, 39, 2));
  printf(" | depois (40-%d) rpm %.0f som %.1f vib %.1f", fim_falha, media(JANELA_FALHA, fim_falha, 0), media(JANELA_FALHA, fim_falha, 1), media(JANELA_FALHA, fim_falha, 2));
  printf(" | janela 60 rpm %ld som %.1f vib %ld | %s\n", cs_jan[JANELA_FIM].rpm, cs_jan[JANELA_FIM].som, cs_jan[JANELA_FIM].vib,
         cs_falhas ? "FALHOU" : "conferido");
  return cs_falhas ? 1 : 0;
}
