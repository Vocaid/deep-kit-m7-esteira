// VOCAID DEEP - Fisica IA na bancada - M7: esteira orquestrada no Arduino Mega (kit KY)
// Tres sensores, um escore: optico (KY-010, rpm) + som (KY-037, rms/pico) + vibracao (KY-002, bordas por janela).
// Janela de 1 s -> 30 janelas de calibracao (media/desvio por canal) -> z-score por canal -> score = max|z|.
// ALERTA so apos 2 janelas seguidas com score > 3,0; e TRAVADO (sem rearme automatico): o rele corta o motor,
// o buzzer toca, o LED vermelho acende, e so o reset da placa rearma. Metodo e estatistica calibrada, nao rede neural.
// Saida CSV: janela,rpm,som_rms,som_pico,vib,score,estado   (linhas com # sao narracao)
//
// Pinos (Mega): KY-010 D2 (INT4) | KY-037 A0 | KY-002 D3 (INT5) | KY-019 rele IN D7 | LED_OK D4 | LED_ALERTA D5 | buzzer D6
//               ULN2003 IN1-4 D8-D11 (28BYJ-48, so com MOTOR_PASSO 1) | KY-028 termistor A1 (desligado: CANAL_TEMP 0)
// Motor do processo (padrao, MOTOR_PASSO 0): Akiyama AK280 (12 V DC) com volante de latao, chaveado SO pelo KY-019 via motorEnergizado().
// Uma aleta de papel no aro do volante passa pela fenda do KY-010. Falha da demo: atrito ao vivo (cotonete num cabo) apos o "# calibrado:".

#ifndef MOTOR_PASSO
#define MOTOR_PASSO 0                     // 0 = motor DC AK280 pelo rele (padrao); 1 = 28BYJ-48 + ULN2003 (caminho antigo, alvo lento da visao)
#endif

#ifndef CANAL_TEMP
#define CANAL_TEMP 0                      // 1 = quarto canal (KY-028 em A1, leitura bruta do ADC); entrega desligado
#endif

const int PINO_OPTICO = 2, PINO_VIB = 3, PINO_SOM = A0, PINO_TEMP = A1;
const int PINO_RELE = 7, PINO_LED_OK = 4, PINO_LED_ALERTA = 5, PINO_BUZZER = 6;
#if MOTOR_PASSO
const int PINOS_BOBINA[4] = {8, 9, 10, 11};
#endif
const bool RELE_ATIVO_BAIXO = false;      // KY-019: S aciona um NPN -> ativo em ALTO; confirme na checagem de bancada

const unsigned long JANELA_MS = 1000UL;   // uma janela por segundo
const unsigned long AMOSTRA_US = 1000UL;  // KY-037 amostrado a cada ~1 ms (~1 kHz)
#if MOTOR_PASSO
const unsigned long PASSO_US = 2000UL;    // 28BYJ-48: ~2 ms por meio passo (nao bloqueante, via micros)
#endif
const int JANELAS_AQUECE = 3;             // as 3 primeiras janelas sao descartadas (AQUECENDO): DC do KY-037 e partida do motor
const int JANELAS_CALIB = 30;             // as 30 janelas seguintes calibram (estado CALIBRANDO)
const int JANELAS_PARA_ALERTA = 2;        // janelas seguidas com score > LIMIAR_Z para disparar
const float LIMIAR_Z = 3.0f;              // comparacao ESTRITA: score == 3,0 nao conta
const float DESVIO_MIN = 1e-3f;           // so protecao contra divisao por zero em zscore(); os pisos reais sao PISO[] abaixo
#ifndef PULSOS_POR_VOLTA
#define PULSOS_POR_VOLTA 1                // aletas no KY-010: 1 aleta de papel no aro do volante. A ~2000 rpm (33 rev/s) a contagem por janela de 1 s e ~33
#endif
// Guardas do KY-010 (micros): veja aceitarPulso().
const unsigned long GUARDA_MESMO_TIPO_US = 2000UL;  // entre duas bordas CONTADAS: ate 500 Hz (30 000 rpm com 1 aleta)
const unsigned long GUARDA_QUALQUER_US = 200UL;     // desde QUALQUER borda: rejeita salto de contato/optico na entrada e na saida da aleta

const int N_CANAIS = 3 + CANAL_TEMP;      // 0 = rpm, 1 = som_rms, 2 = vib, (3 = temperatura bruta)

// Pisos do desvio por canal, em unidades do canal. Sem eles, um canal que calibra quase constante (rpm e vib sao
// contagens inteiras) daria desvio ~0 e qualquer degrau de 1 contagem viraria z enorme: disparo falso.
const float PISO[4] = {
  60.0f / PULSOS_POR_VOLTA,               // rpm: um pulso a mais ou a menos na janela = 60/PULSOS_POR_VOLTA rpm (um degrau de contagem)
  3.0f,                                   // som_rms: ~3 contagens do ADC de 10 bits (ruido de quantizacao do KY-037)
  2.0f,                                   // vib: um evento do KY-002 = 2 bordas CHANGE (sobe e desce)
  3.0f                                    // temperatura bruta (CANAL_TEMP): ~3 contagens do ADC
};

// ---------- estado compartilhado com as interrupcoes: SO estes dois, volatile, lidos por copia atomica ----------
volatile unsigned long g_pulsos = 0;      // pulsos opticos validos na janela corrente
volatile unsigned long g_bordas = 0;      // TODAS as bordas do KY-002 na janela corrente
// unsigned long tem 4 bytes no AVR (8 bits): ler em loop() enquanto a ISR incrementa pode dar leitura rasgada.
// Por isso fimDeJanela() copia e zera os dois dentro de noInterrupts()/interrupts().

// KY-010 (optico): duas guardas, independentes da polaridade do modulo (LOW pode ser aleta presente OU ausente).
//  - GUARDA_MESMO_TIPO_US = 2000 us entre bordas contadas: ate 500 Hz (30 000 rpm com 1 aleta). O AK280 (etiqueta ~4600 rpm
//    em vazio) com 1 aleta chega a ~77 pulsos/s (periodo ~13 ms); a ~2000 rpm sao ~33/s. Qualquer limite <= 3 ms aceita >= 100 Hz.
//  - GUARDA_QUALQUER_US = 200 us desde QUALQUER borda (ultimaBordaUs e atualizada em toda borda): rejeita o salto de contato
//    nas duas transicoes (entrada e saida da aleta). Com isso nao importa qual das duas bordas e a LOW: se a LOW for a saida da
//    aleta, ela vem t_aleta depois da entrada e NAO e mais rejeitada (a guarda antiga de 2 ms em millis() a rejeitava).
//    Regra da aleta: o arco coberto e o arco livre precisam durar > 200 us na rotacao maxima.
bool aceitarPulso(unsigned long agoraUs, unsigned long ultimoAceitoUs, unsigned long ultimaBordaUs, bool nivelBaixo) {
  return nivelBaixo && (agoraUs - ultimoAceitoUs) > GUARDA_MESMO_TIPO_US && (agoraUs - ultimaBordaUs) > GUARDA_QUALQUER_US;
}

void aoPulsoOptico() {
  static unsigned long ultimaBordaUs = 0, ultimoAceitoUs = 0;
  unsigned long agora = micros();
  if (aceitarPulso(agora, ultimoAceitoUs, ultimaBordaUs, digitalRead(PINO_OPTICO) == LOW)) {
    g_pulsos = g_pulsos + 1;
    ultimoAceitoUs = agora;
  }
  ultimaBordaUs = agora;
}

// KY-002 (vibracao): conta TODAS as bordas, SEM debounce. Contraste didatico com o KY-010 acima: aqui o "ruido" de contato
// (a esfera/mola quicando) E o sinal. Debouncear apagaria justamente a feature. Quanto mais a esteira treme, mais bordas por janela.
void aoBordaVibracao() {
  g_bordas = g_bordas + 1;
}

// ---------- funcoes puras (testadas no AUTO-TESTE) ----------
float zscore(float x, float media, float desvio) {
  float d = desvio > DESVIO_MIN ? desvio : DESVIO_MIN;
  return (x - media) / d;
}

float fundir(const float* z, int n) {      // score = max |z| sobre os canais
  float m = 0.0f;
  for (int i = 0; i < n; i++) {
    float a = z[i] < 0.0f ? -z[i] : z[i];
    if (a > m) m = a;
  }
  return m;
}

// Desvio calibrado -> desvio usado: nunca abaixo do piso do canal (o piso nao baixa um desvio maior).
float limitarDesvio(float desvio, float piso) { return desvio > piso ? desvio : piso; }

// Calibracao suspeita: rpm medio abaixo de um degrau de contagem = motor parado/travado na calibracao. Linha de base ruim.
bool calibracaoSuspeita(float media_rpm) { return media_rpm < PISO[0]; }

// Uma janela: x[] cru, media[] e desvio[] da calibracao -> score.
float scoreJanela(const float* x, const float* media, const float* desvio, int n) {
  float z[4];
  for (int i = 0; i < n; i++) z[i] = zscore(x[i], media[i], desvio[i]);
  return fundir(z, n);
}

// decidir(): sequencia de janelas -> ALERTA. streak conta janelas SEGUIDAS com score > LIMIAR_Z (qualquer janela calma zera).
// Travado: depois de disparar, nunca volta (sem rearme automatico). Devolve true = ALERTA.
bool decidir(float score, int streak, bool travado, int* streak_novo) {
  *streak_novo = (score > LIMIAR_Z) ? streak + 1 : 0;
  return travado || (*streak_novo >= JANELAS_PARA_ALERTA);
}

// ---------- atuadores ----------
// motorEnergizado() e o UNICO escritor do pino do rele.
void motorEnergizado(bool ligar) {
  digitalWrite(PINO_RELE, ((ligar ^ RELE_ATIVO_BAIXO) ? HIGH : LOW));
}

#if MOTOR_PASSO
// 28BYJ-48 em meio passo (8 fases). Nao bloqueante: um passo quando passam PASSO_US.
const byte FASES[8][4] = {{1,0,0,0},{1,1,0,0},{0,1,0,0},{0,1,1,0},{0,0,1,0},{0,0,1,1},{0,0,0,1},{1,0,0,1}};
void bobinasDesligadas() { for (int i = 0; i < 4; i++) digitalWrite(PINOS_BOBINA[i], LOW); }
void passoNaoBloqueante(bool girar) {
  static unsigned long ultimo = 0;
  static byte fase = 0;
  if (!girar) { bobinasDesligadas(); return; }
  unsigned long agora = micros();
  if (agora - ultimo < PASSO_US) return;
  ultimo = agora;
  for (int i = 0; i < 4; i++) digitalWrite(PINOS_BOBINA[i], FASES[fase][i] ? HIGH : LOW);
  fase = (fase + 1) & 7;
}
#endif

// ---------- estado do laco ----------
bool g_ok = false;                        // AUTO-TESTE passou
bool g_travado = false;                   // ALERTA disparado (so o reset da placa limpa)
bool g_suspeita = false;                  // calibracao com motor parado: corta o motor, nao arma o ALERTA (so o reset refaz)
int g_streak = 0;
unsigned int g_janela = 0;
unsigned long g_t_janela = 0, g_t_amostra = 0;
float g_dc = 512.0f;                      // nivel DC do KY-037, seguido por media movel exponencial
// Soma dos quadrados do som: d = amostra - DC cabe em +-1023, d*d <= 1 046 529 (cabe em long de 32 bits; em int de 16 bits
// estouraria). ~1000 amostras/janela => soma <= ~1,05e9, abaixo de 4,29e9 (unsigned long), com folga de 4x. Em float tambem
// serviria, mas o inteiro e exato. A resincronizacao em amostrar() garante no maximo 1 amostra por ms.
unsigned long g_soma_q = 0;
unsigned int g_n_amostras = 0;
int g_pico = 0;
// Calibracao (Welford, float): media e M2 por canal
float g_media[4], g_m2[4], g_desvio[4];
int g_n_cal = 0;

void amostrar() {
  unsigned long agora = micros();
  if (agora - g_t_amostra < AMOSTRA_US) return;
  g_t_amostra += AMOSTRA_US;
  if (agora - g_t_amostra >= AMOSTRA_US) g_t_amostra = agora;   // atrasado: resincroniza, nunca acumula amostras
  int s = analogRead(PINO_SOM);
  g_dc += ((float)s - g_dc) * 0.01f;                            // segue o DC (constante de tempo ~100 amostras)
  long d = (long)((float)s - g_dc);
  long a = d < 0 ? -d : d;
  g_soma_q += (unsigned long)(d * d);                           // d e long: produto em 32 bits
  g_n_amostras++;
  if (a > g_pico) g_pico = (int)a;
}

void fimDeJanela() {
  unsigned long pulsos, bordas;
  noInterrupts();                                               // copia atomica e zera: ISR nao pode incrementar no meio
  pulsos = g_pulsos; bordas = g_bordas;
  g_pulsos = 0; g_bordas = 0;
  interrupts();

  unsigned long rpm = pulsos * 60UL / PULSOS_POR_VOLTA;
  float rms = g_n_amostras > 0 ? sqrt((float)g_soma_q / (float)g_n_amostras) : 0.0f;
  int pico = g_pico;
  g_soma_q = 0; g_n_amostras = 0; g_pico = 0;

  float x[4];
  x[0] = (float)rpm; x[1] = rms; x[2] = (float)bordas;
#if CANAL_TEMP
  x[3] = (float)analogRead(PINO_TEMP);
#endif

  g_janela++;
  float score = 0.0f;
  bool alerta = g_travado;
  const char* estado;
  if (g_janela <= (unsigned int)JANELAS_AQUECE) {               // descartada: nao entra no Welford
    digitalWrite(PINO_LED_OK, (g_janela & 1) ? HIGH : LOW);
    estado = "AQUECENDO";
  } else if (g_janela <= (unsigned int)(JANELAS_AQUECE + JANELAS_CALIB)) {
    g_n_cal++;
    for (int i = 0; i < N_CANAIS; i++) {
      float delta = x[i] - g_media[i];
      g_media[i] += delta / (float)g_n_cal;
      g_m2[i] += delta * (x[i] - g_media[i]);
    }
    if (g_n_cal == JANELAS_CALIB) {
      Serial.print(F("# calibrado:"));
      for (int i = 0; i < N_CANAIS; i++) {
        g_desvio[i] = limitarDesvio(sqrt(g_m2[i] / (float)(g_n_cal - 1)), PISO[i]);
        Serial.print(F(" c")); Serial.print(i); Serial.print(F(" media=")); Serial.print(g_media[i], 1);
        Serial.print(F(" desvio=")); Serial.print(g_desvio[i], 2);
      }
      Serial.println();
      digitalWrite(PINO_LED_OK, HIGH);
      if (calibracaoSuspeita(g_media[0])) {
        g_suspeita = true;
        motorEnergizado(false);                                 // sem linha de base a IA ficaria inerte com o rele fechado: corta
        Serial.println(F("# SUSPEITA: motor cortado -- de reset com o motor girando"));
      }
    } else {
      digitalWrite(PINO_LED_OK, (g_janela & 1) ? HIGH : LOW);   // pisca durante a calibracao
    }
    estado = "CALIBRANDO";
  } else if (g_suspeita) {                                      // linha de base ruim: motor cortado, nunca arma, nunca dispara
    digitalWrite(PINO_LED_OK, (g_janela & 1) ? HIGH : LOW);
    estado = "SUSPEITA";
  } else {
    score = scoreJanela(x, g_media, g_desvio, N_CANAIS);
    alerta = decidir(score, g_streak, g_travado, &g_streak);
    if (alerta && !g_travado) {                                 // disparo: acontece uma unica vez
      g_travado = true;
      motorEnergizado(false);
      digitalWrite(PINO_LED_OK, LOW);
      digitalWrite(PINO_LED_ALERTA, HIGH);
      digitalWrite(PINO_BUZZER, HIGH);
      Serial.println(F("# ALERTA TRAVADO: rele (KY-019) abriu e cortou o motor; so o reset da placa rearma (sem rearme automatico)"));
    }
    estado = alerta ? "ALERTA" : "NORMAL";
  }

  Serial.print(g_janela); Serial.print(',');
  Serial.print(rpm); Serial.print(',');
  Serial.print(rms, 1); Serial.print(',');
  Serial.print(pico); Serial.print(',');
  Serial.print(bordas); Serial.print(',');
  Serial.print(score, 1); Serial.print(',');
  Serial.println(estado);
}

// ---------- AUTO-TESTE ----------
bool perto(float a, float b, float tol) { return (a > b ? a - b : b - a) <= tol; }

// Roda uma sequencia de scores por decidir(); devolve o estado final e a janela (1-based) do primeiro disparo (0 = nunca).
bool simular(const float* scores, int n, int* primeira) {
  int streak = 0; bool travado = false; *primeira = 0;
  for (int i = 0; i < n; i++) {
    bool alerta = decidir(scores[i], streak, travado, &streak);
    if (alerta && !travado) { *primeira = i + 1; travado = true; }
  }
  return travado;
}

int autoTeste() {
  int certos = 0, total = 0;
  // Calibracao fixa dos vetores: desvios BRUTOS 20 / 1 / 0,5 (todos abaixo dos pisos) -> limitarDesvio() -> 60 / 3 / 2
  //   medias: rpm 600 | som_rms 50 | vib 40
  const float MU[3] = {600.0f, 50.0f, 40.0f}, SD_BRUTO[3] = {20.0f, 1.0f, 0.5f};
  float SD[3];
  for (int i = 0; i < 3; i++) SD[i] = limitarDesvio(SD_BRUTO[i], PISO[i]);
  // janelas (rpm, som_rms, vib) -> score = max|z| com desvios 60 / 3 / 2 (contas feitas a mao a partir da regra)
  const float W[7][3] = {
    {600.0f, 50.0f, 40.0f},   // calma: z = 0, 0, 0                                  -> 0,0
    {630.0f, 48.5f, 41.0f},   // calma com folga: 30/60 = 0,5; -1,5/3 = -0,5; 1/2 = 0,5 -> 0,5
    {900.0f, 50.0f, 40.0f},   // so o optico domina: 300/60 = 5                      -> 5,0
    {600.0f, 32.0f, 40.0f},   // so o som domina: -18/3 = -6 (sinal negativo conta)  -> 6,0
    {600.0f, 50.0f, 54.0f},   // so a vibracao domina: 14/2 = 7                       -> 7,0
    {780.0f, 50.0f, 40.0f},   // exatamente no limiar: 180/60 = 3,0                   -> 3,0 (nao e > 3,0)
    {660.0f, 50.0f, 40.0f}    // um degrau de contagem de rpm (1 pulso): 60/60 = 1    -> 1,0 (o piso evita falso disparo)
  };
  const float W_ESP[7] = {0.0f, 0.5f, 5.0f, 6.0f, 7.0f, 3.0f, 1.0f};
  for (int i = 0; i < 7; i++) {
    float r = scoreJanela(W[i], MU, SD, 3);
    bool ok = perto(r, W_ESP[i], 0.001f);
    certos += ok; total++;
    Serial.print(F("janela ")); Serial.print(i); Serial.print(F(" score ")); Serial.print(r, 1);
    Serial.print(F(" esperado ")); Serial.print(W_ESP[i], 1); Serial.println(ok ? F(" =") : F(" X"));
  }
  // pisos: desvio brutos menores sobem ao piso; maiores ficam; pisos por canal (unidades do canal)
  {
    bool ok = perto(limitarDesvio(20.0f, PISO[0]), 60.0f, 0.001f) && perto(limitarDesvio(100.0f, PISO[0]), 100.0f, 0.001f)
           && perto(limitarDesvio(1.0f, PISO[1]), 3.0f, 0.001f) && perto(limitarDesvio(0.5f, PISO[2]), 2.0f, 0.001f);
    certos += ok; total++;
    Serial.print(F("pisos (rpm 60, som 3, vib 2; maior desvio fica)")); Serial.println(ok ? F(" =") : F(" X"));
  }
  // aceitarPulso(): duas guardas (2000 us entre contadas, 200 us desde qualquer borda), so em nivel LOW. Tempos em us.
  {
    const unsigned long A = 1000000UL;                           // um pulso aceito em A
    bool v1 = aceitarPulso(A, 0UL, 0UL, true);                   // pulso real apos longo silencio: A-0 > 2000 e > 200 -> true
    bool v2 = !aceitarPulso(A + 50UL, A, A, true);               // salto 50 us apos a borda aceita: 50 <= 200 -> false
    bool v3 = !aceitarPulso(A + 5080UL, A, A + 5000UL, true);    // LOW 80 us apos uma borda HIGH (saida da aleta): 80 <= 200 -> false
    bool v4 = aceitarPulso(A + 13000UL, A, A + 6000UL, true);    // 13 000 us depois (4600 rpm): 13000 > 2000 e 7000 > 200 -> true
    bool v5 = !aceitarPulso(A + 1500UL, A, A + 800UL, true);     // 1500 us apos a aceita: 1500 <= 2000 -> false (qualquer-borda 700 passa)
    bool v6 = !aceitarPulso(A + 13000UL, A, A + 6000UL, false);  // mesmas folgas do v4, mas nivel HIGH -> false
    bool ok = v1 && v2 && v3 && v4 && v5 && v6;
    certos += ok; total++;
    Serial.print(F("aceitarPulso (longo silencio sim; salto 50us e 80us nao; 13000us sim; 1500us nao; HIGH nao)")); Serial.println(ok ? F(" =") : F(" X"));
  }
  // guarda de divisao: desvio 0 vira 1e-3, entao x - media = 1 da z = 1000 (e nao divisao por zero)
  {
    float r = zscore(1.0f, 0.0f, 0.0f);
    bool ok = perto(r, 1000.0f, 0.05f);
    certos += ok; total++;
    Serial.print(F("guarda de divisao z ")); Serial.print(r, 1); Serial.println(ok ? F(" =") : F(" X"));
  }
  // calibracao suspeita: rpm medio < 60 (um degrau) = motor parado
  {
    bool ok = calibracaoSuspeita(0.0f) && calibracaoSuspeita(59.0f) && !calibracaoSuspeita(60.0f) && !calibracaoSuspeita(600.0f);
    certos += ok; total++;
    Serial.print(F("calibracao suspeita (0 e 59 sim; 60 e 600 nao)")); Serial.println(ok ? F(" =") : F(" X"));
  }
  // sequencias de score -> decidir (limiar 3,0 estrito, 2 janelas seguidas, travado)
  const float S_BLIP[5]   = {0.5f, 5.0f, 0.5f, 5.0f, 0.5f};   // picos isolados: NAO dispara
  const float S_DUAS[2]   = {5.0f, 5.0f};                      // duas seguidas: dispara na 2a
  const float S_LIMIAR[4] = {3.0f, 3.0f, 3.0f, 3.0f};          // exatamente 3,0: mantem o estado, nunca dispara
  const float S_ACIMA[2]  = {3.01f, 3.01f};                    // logo acima: dispara na 2a
  const float S_TRAVA[4]  = {5.0f, 5.0f, 0.5f, 0.5f};          // dispara na 2a e continua em ALERTA mesmo calmo (travado)
  const float S_ZERA[4]   = {5.0f, 0.5f, 5.0f, 5.0f};          // a janela calma zera a contagem: dispara so na 4a
  const float* S[6] = {S_BLIP, S_DUAS, S_LIMIAR, S_ACIMA, S_TRAVA, S_ZERA};
  const int S_N[6] = {5, 2, 4, 2, 4, 4};
  const int S_PRIM[6] = {0, 2, 0, 2, 2, 4};
  const bool S_FIM[6] = {false, true, false, true, true, true};
  const char* S_NOME[6] = {"blip", "duas", "limiar", "acima", "trava", "zera"};
  for (int i = 0; i < 6; i++) {
    int prim; bool fim = simular(S[i], S_N[i], &prim);
    bool ok = (prim == S_PRIM[i]) && (fim == S_FIM[i]);
    certos += ok; total++;
    Serial.print(F("sequencia ")); Serial.print(S_NOME[i]); Serial.print(F(" dispara em ")); Serial.print(prim);
    Serial.print(fim ? F(" final ALERTA") : F(" final NORMAL")); Serial.println(ok ? F(" =") : F(" X"));
  }
  Serial.print(F("AUTO-TESTE: ")); Serial.print(certos); Serial.print('/'); Serial.print(total);
  Serial.println(certos == total ? F(" -> PASS") : F(" -> VERIFICAR"));
  return certos == total;
}

void setup() {
  motorEnergizado(false);                                       // nivel de rele desligado ANTES de virar saida: sem pulso no boot
  pinMode(PINO_RELE, OUTPUT);
  pinMode(PINO_LED_OK, OUTPUT); pinMode(PINO_LED_ALERTA, OUTPUT); pinMode(PINO_BUZZER, OUTPUT);
#if MOTOR_PASSO
  for (int i = 0; i < 4; i++) pinMode(PINOS_BOBINA[i], OUTPUT);
#endif
  digitalWrite(PINO_LED_OK, LOW); digitalWrite(PINO_LED_ALERTA, LOW); digitalWrite(PINO_BUZZER, LOW);
#if MOTOR_PASSO
  bobinasDesligadas();
#endif
  pinMode(PINO_OPTICO, INPUT_PULLUP);
  pinMode(PINO_VIB, INPUT_PULLUP);
  Serial.begin(115200); delay(300);
  Serial.println(F("== VOCAID DEEP - M7 esteira orquestrada (KY-010 + KY-037 + KY-002) no Arduino Mega =="));
  Serial.println(F("# metodo: estatistica calibrada (z-score); upgrade: MLP int8 como no modulo de impacto"));
  Serial.print(F("# ")); Serial.print(JANELAS_AQUECE); Serial.print(F(" janelas descartadas + ")); Serial.print(JANELAS_CALIB); Serial.print(F(" de calibracao | ALERTA com score > "));
  Serial.print(LIMIAR_Z, 1); Serial.print(F(" em ")); Serial.print(JANELAS_PARA_ALERTA);
  Serial.println(F(" janelas seguidas | travado ate o reset da placa"));
  g_ok = autoTeste();
  if (!g_ok) { Serial.println(F("# AUTO-TESTE falhou: motor mantido desligado")); return; }

  long soma = 0;
  for (int i = 0; i < 16; i++) soma += analogRead(PINO_SOM);
  g_dc = (float)soma / 16.0f;                                   // DC inicial do KY-037
  attachInterrupt(digitalPinToInterrupt(PINO_OPTICO), aoPulsoOptico, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PINO_VIB), aoBordaVibracao, CHANGE);
  Serial.println(F("janela,rpm,som_rms,som_pico,vib,score,estado"));
  motorEnergizado(true);                                        // so liga o motor com o auto-teste aprovado
  g_t_janela = millis(); g_t_amostra = micros();
}

void loop() {
  if (!g_ok) return;
#if MOTOR_PASSO
  passoNaoBloqueante(!g_travado && !g_suspeita);               // o 28BYJ-48 tambem para no ALERTA e na SUSPEITA
#endif
  amostrar();
  if (millis() - g_t_janela >= JANELA_MS) {
    g_t_janela += JANELA_MS;
    fimDeJanela();
  }
}
