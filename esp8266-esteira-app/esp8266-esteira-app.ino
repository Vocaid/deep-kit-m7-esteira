// M7 / Task 13 - NodeMCU ESP8266: o app do Vocaid liga a esteira (rele A, em serie com o rele B do Mega).
// Le GET /api/connect/v1/research-studio/workspaces/{id}/head por HTTPS (CA raiz fixada, sem setInsecure)
// e fecha o rele A SOMENTE enquanto contents.meta disser "esteira: ligada" e a leitura for recente.
// Qualquer falha (Wi-Fi, NTP, TLS, HTTP != 200, JSON, meta ausente, resposta velha) = rele A ABERTO.
// A chave e a senha do Wi-Fi nunca vao para a serial.
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <time.h>
#include <ArduinoJson.h>
#include "segredos.h"      // gitignored; copie de segredos.exemplo.h
#include "certificados.h"  // CAs raiz publicas
#include "logica.h"        // logica pura, testada no host

// ---------------- configuracao ----------------
#define MODO_AULA 1                          // 1: consulta a cada 10 s nos primeiros 20 min depois do boot; 0: sempre 180 s
const uint32_t INTERVALO_AULA_MS = 10000UL;
const uint32_t JANELA_AULA_MS = 20UL * 60UL * 1000UL;
const uint32_t INTERVALO_NORMAL_MS = 180000UL;
const char* const HOST = "SEU_HOST_VOCAID";  // host do seu ambiente Vocaid (veja o README)
const uint16_t PORTA = 443;
const uint8_t PINO_RELE_A = D1;              // GPIO5 -> IN do rele A
const bool RELE_ATIVO_BAIXO = true;          // padrao dos modulos comuns (energizam em LOW), igual aos sketches do Mega. CONFIRA NA BANCADA com o motor desligado (README)
const uint8_t PINO_LED = LED_BUILTIN;        // GPIO2, o LED da placa acende em LOW
const uint32_t TEMPO_NTP_MS = 15000UL;
// Pior caso de UMA consulta travada: DNS 3 s + conexao/TLS 4 s + cabecalho 4 s + corpo 4 s (cada espera tem seu timeout).
// Antes de consultar, se a resposta ficaria velha antes desse prazo acabar, o rele abre primeiro.
const uint32_t TIMEOUT_MS = 4000UL;
const uint32_t TIMEOUT_DNS_MS = 3000UL;
const uint32_t POLL_MAX_MS = TIMEOUT_DNS_MS + 3 * TIMEOUT_MS;
// Contador de reinicios na memoria RTC (sobrevive a WDT e excecao; nao a queda total de energia)
const uint32_t RTC_MAGICO = 0x45535431UL;  // "EST1"
const uint32_t REINICIOS_LIMITE = 3;
const uint32_t ESPERA_SEM_AULA_MS = 60000UL;
const uint32_t SAUDAVEL_MS = 10UL * 60UL * 1000UL;
const time_t HORA_MINIMA = 1767225600;       // 2026-01-01: abaixo disso o relogio nao foi acertado

// ---------------- estado ----------------
BearSSL::X509List g_ancoras;
bool g_releFechado = false;
bool g_respostaOk = false;     // a ultima consulta deu certo
bool g_marcador = false;       // e o meta dizia "esteira: ligada"
bool g_temOk = false;
uint32_t g_ultimoOkMs = 0;
uint32_t g_proximaMs = 0;
uint32_t g_inicioMs = 0;
int g_mfln = -1;               // -1 nao testado, 0 sem MFLN, 1 com MFLN (4096)
String g_ultimoMotivo;
bool g_semAula = false;        // quedas do firmware em sequencia: sem modo aula
bool g_contadorZerado = false;
bool g_heapImpresso = false;
char g_fingerprint[9] = "";

// Unico escritor do pino do rele A.
void releA(bool fechar) {
  g_releFechado = fechar;
  digitalWrite(PINO_RELE_A, (fechar ^ RELE_ATIVO_BAIXO) ? HIGH : LOW);
  digitalWrite(PINO_LED, fechar ? LOW : HIGH);  // LED da placa acende em LOW: acesso = rele fechado
}

// Abre o rele e diz por que (so imprime quando o motivo muda ou o rele acabou de abrir).
void abrirPor(const char* motivo) {
  bool mudou = g_releFechado || g_ultimoMotivo != motivo;
  releA(false);
  if (mudou) { Serial.print(F("# rele A aberto: ")); Serial.println(motivo); }
  g_ultimoMotivo = motivo;
}

uint32_t intervaloAtual() {
#if MODO_AULA
  if (g_semAula) return INTERVALO_NORMAL_MS;
  return (millis() - g_inicioMs < JANELA_AULA_MS) ? INTERVALO_AULA_MS : INTERVALO_NORMAL_MS;
#else
  return INTERVALO_NORMAL_MS;
#endif
}

bool relogioAcertado() { return time(nullptr) >= HORA_MINIMA; }

void iniciarNtp() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  uint32_t t0 = millis();
  while (!relogioAcertado() && millis() - t0 < TEMPO_NTP_MS) { delay(200); }
}

// Faz uma consulta. Atualiza g_respostaOk/g_marcador. Devolve o motivo da falha, ou nullptr se deu certo.
const char* consultar() {
  if (WiFi.status() != WL_CONNECTED) return "wi-fi fora";
  if (!relogioAcertado()) {
    iniciarNtp();
    if (!relogioAcertado()) return "ntp falhou";
  }
  BearSSL::WiFiClientSecure cliente;
  cliente.setTrustAnchors(&g_ancoras);
  cliente.setX509Time(time(nullptr));
  cliente.setTimeout(TIMEOUT_MS);
  IPAddress ip;
  if (!WiFi.hostByName(HOST, ip, TIMEOUT_DNS_MS)) return "dns falhou";
  if (g_mfln < 0) g_mfln = cliente.probeMaxFragmentLength(HOST, PORTA, 4096) ? 1 : 0;
  if (g_mfln == 1) cliente.setBufferSizes(4096, 512);  // so com MFLN o servidor respeita registros de 4 KB; senao fica o padrao

  HTTPClient https;
  https.setReuse(false);
  https.useHTTP10(true);  // sem Transfer-Encoding: chunked, o corpo vem puro no stream
  https.setTimeout(TIMEOUT_MS);
  String url = String("https://") + HOST + "/api/connect/v1/research-studio/workspaces/" + VOCAID_WORKSPACE + "/head";
  if (!https.begin(cliente, url)) return "tls falhou (begin)";
  https.addHeader("Authorization", String("Bearer ") + VOCAID_CHAVE);
  https.addHeader("Accept", "application/json");
  int codigo = https.GET();
  if (codigo <= 0) {
    static char motivo[40];
    snprintf(motivo, sizeof motivo, "tls/rede falhou (erro ssl %d)", cliente.getLastSSLError());
    https.end();
    return motivo;
  }
  if (codigo != 200) {
    static char motivo[24];
    snprintf(motivo, sizeof motivo, "http %d", codigo);
    https.end();
    return motivo;
  }

  JsonDocument filtro;
  filtro["fingerprint"] = true;
  filtro["contents"]["meta"] = true;
  JsonDocument doc;
  DeserializationError erro = deserializeJson(doc, https.getStream(), DeserializationOption::Filter(filtro));
  if (!g_heapImpresso) {
    g_heapImpresso = true;
    Serial.print(F("# heap livre: ")); Serial.print(ESP.getFreeHeap());
    Serial.print(F(" B, maior bloco: ")); Serial.println(ESP.getMaxFreeBlockSize());
  }
  https.end();
  if (erro) return "json invalido";
  const char* meta = doc["contents"]["meta"] | (const char*)nullptr;
  if (meta == nullptr) return "meta ausente";
  const char* fp = doc["fingerprint"] | "";
  if (strncmp(g_fingerprint, fp, 8) != 0) {
    strlcpy(g_fingerprint, fp, sizeof g_fingerprint);
    Serial.print(F("# commit novo no head: ")); Serial.println(g_fingerprint);
  }
  g_marcador = marcadorLigada(meta);
  return nullptr;
}

// Conta so as quedas do firmware (WDT de hardware, excecao, WDT de software): protege a cota da organizacao.
// Botao RESET, regravacao pelo USB e energizacao NAO contam (e zeram a sequencia).
bool reinicioPorFalha(uint32_t motivo) {
  return motivo == REASON_WDT_RST || motivo == REASON_EXCEPTION_RST || motivo == REASON_SOFT_WDT_RST;
}

void verificarReinicios() {
  uint32_t rtc[2] = {0, 0};
  ESP.rtcUserMemoryRead(0, rtc, sizeof rtc);
  uint32_t n = 0;
  if (reinicioPorFalha(ESP.getResetInfoPtr()->reason)) n = (rtc[0] == RTC_MAGICO) ? rtc[1] + 1 : 1;
  rtc[0] = RTC_MAGICO; rtc[1] = n;
  ESP.rtcUserMemoryWrite(0, rtc, sizeof rtc);
  if (n >= REINICIOS_LIMITE) {
    g_semAula = true;
    g_proximaMs = millis() + ESPERA_SEM_AULA_MS;
    Serial.print(F("# ")); Serial.print(n);
    Serial.println(F(" quedas seguidas (WDT/excecao): sem modo aula, primeira consulta em 60 s (protege a cota; RESET ou desligar e ligar zera)"));
  }
}

void setup() {
  // nivel seguro (aberto) ANTES de virar saida: o pino nunca fecha o rele na partida
  digitalWrite(PINO_RELE_A, (false ^ RELE_ATIVO_BAIXO) ? HIGH : LOW);
  pinMode(PINO_RELE_A, OUTPUT);
  digitalWrite(PINO_LED, HIGH);
  pinMode(PINO_LED, OUTPUT);
  releA(false);
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println(F("# esp8266-esteira-app: rele A so fecha com 'esteira: ligada' no meta do artigo"));

  int total = 0;
  int ok = autoTesteEsteira(&total);
  Serial.print(F("AUTO-TESTE: ")); Serial.print(ok); Serial.print('/'); Serial.print(total);
  Serial.println(ok == total ? F(" -> PASS") : F(" -> FAIL"));
  if (ok != total) {
    Serial.println(F("# rele A aberto: auto-teste falhou, travado"));
    while (true) { delay(1000); }
  }

  g_ancoras.append(PEM_ISRG_ROOT_X1);
  g_ancoras.append(PEM_ISRG_ROOT_YR);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  g_inicioMs = millis();
  g_proximaMs = millis();
  verificarReinicios();
  Serial.print(F("# modo aula: ")); Serial.println(g_semAula ? F("desligado (quedas seguidas), 180 s") : (MODO_AULA ? F("10 s por 20 min, depois 180 s") : F("180 s")));
  abrirPor("aguardando primeira consulta");
}

void loop() {
  uint32_t agora = millis();
  if (!g_contadorZerado && agora - g_inicioMs >= SAUDAVEL_MS) {
    g_contadorZerado = true;
    uint32_t rtc[2] = {RTC_MAGICO, 0};
    ESP.rtcUserMemoryWrite(0, rtc, sizeof rtc);
  }
  if (WiFi.status() != WL_CONNECTED) {  // perda do Wi-Fi age na hora, nao so na proxima consulta
    g_respostaOk = false;
    g_marcador = false;
    abrirPor("wi-fi fora");
  }
  if ((int32_t)(agora - g_proximaMs) >= 0) {
    if (g_releFechado) {  // uma consulta travada nao pode segurar o rele fechado com resposta velha
      uint64_t idadeAntes = g_temOk ? (uint64_t)(millis() - g_ultimoOkMs) : 0xFFFFFFFFull;
      if (idadeAntes + POLL_MAX_MS > 3ULL * intervaloAtual()) abrirPor("consulta pode demorar mais que a validade");
    }
    const char* falha = consultar();
    g_proximaMs = millis() + intervaloAtual();
    if (falha != nullptr) {
      g_respostaOk = false;
      g_marcador = false;
      abrirPor(falha);
    } else {
      g_respostaOk = true;
      g_temOk = true;
      g_ultimoOkMs = millis();
    }
  }

  // decisao reavaliada a cada volta: a resposta tambem envelhece
  uint32_t idade = g_temOk ? (millis() - g_ultimoOkMs) : 0xFFFFFFFFu;
  bool autorizada = esteiraAutorizada(g_respostaOk, g_marcador, idade, intervaloAtual());
  if (autorizada) {
    if (!g_releFechado) { releA(true); Serial.println(F("# rele A fechado: meta diz esteira ligada")); g_ultimoMotivo = ""; }
  } else if (g_respostaOk && !g_marcador) {
    abrirPor("meta sem 'esteira: ligada'");
  } else if (g_respostaOk) {
    abrirPor("resposta velha");
  }
  delay(50);
}
