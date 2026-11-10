// Logica pura da esteira (relé A): sem Arduino.h. Testada no host (teste-host/) e no boot do NodeMCU.
// So <stdint.h>, <string.h>, <ctype.h>.
#pragma once
#include <stdint.h>
#include <string.h>
#include <ctype.h>

namespace esteira_logica {
inline bool eLetra(char c) {  // letra, digito, '_' ou byte UTF-8: continua a palavra
  unsigned char u = (unsigned char)c;
  return isalnum(u) || u == '_' || u >= 128;
}
inline bool eSeparador(char c) { return c == ' ' || c == '\t' || c == ':' || c == '=' || c == '"' || c == '\'' || c == '-'; }
// compara 'n' bytes de s com a palavra minuscula 'p', sem diferenciar caixa
inline bool igualMin(const char* s, const char* p, size_t n) {
  for (size_t i = 0; i < n; i++) {
    if (s[i] == '\0' || tolower((unsigned char)s[i]) != p[i]) return false;
  }
  return true;
}
inline const char* pularEspacos(const char* c) {
  while (*c == ' ' || *c == '\t' || *c == '\r') c++;
  return c;
}
// O que pode vir depois de "ligada":
//  - texto puro: so fim, quebra de linha, ou espacos ate o fim/quebra de linha;
//  - valor que abriu com aspas: a aspa de fechamento, depois so espacos e entao ',', '}', fim ou quebra de linha.
inline bool fimDeValor(const char* c, bool entreAspas) {
  if (entreAspas) {
    if (*c != '"') return false;
    c = pularEspacos(c + 1);
    return *c == '\0' || *c == '\n' || *c == ',' || *c == '}';
  }
  c = pularEspacos(c);
  return *c == '\0' || *c == '\n';
}
}  // namespace esteira_logica

// Convencao do operador: no campo meta do artigo, a palavra "esteira" seguida do valor "ligada"
// na mesma linha ou no mesmo par JSON ("esteira: ligada", {"esteira":"ligada"}), sem diferenciar caixa.
// "desligada" NAO conta (a palavra "ligada" tem de comecar uma palavra) e nada pode seguir "ligada" na linha:
// em texto puro so espacos; entre aspas so a aspa de fechamento e depois ',', '}' ou o fim da linha (veja fimDeValor).
// "esteira-ligada" (com '-' como separador) vale. Regra a favor da seguranca:
// toda ocorrencia da palavra "esteira" precisa ter o valor "ligada"; qualquer outra (desligada, vazio,
// outra linha) veta. Precisa de pelo menos uma ocorrencia.
inline bool marcadorLigada(const char* meta) {
  using namespace esteira_logica;
  if (meta == nullptr) return false;
  const size_t N = 7;  // "esteira"
  bool viuLigada = false;
  for (const char* p = meta; *p != '\0'; p++) {
    if (!igualMin(p, "esteira", N)) continue;
    if (p != meta && eLetra(p[-1])) continue;  // "pesteira": outra palavra
    if (eLetra(p[N])) continue;                // "esteiras": outra palavra
    const char* v = p + N;
    bool entreAspas = false;  // o ultimo separador antes do valor foi uma aspa: o valor abriu com aspas
    while (eSeparador(*v)) { entreAspas = (*v == '"'); v++; }
    if (igualMin(v, "ligada", 6) && fimDeValor(v + 6, entreAspas)) viuLigada = true;
    else return false;  // desligada, vazio, quebra de linha, outro valor: veta
  }
  return viuLigada;
}

// Autorizada so se a ultima resposta foi OK, o marcador esta ligado e o ultimo OK tem ate 3 intervalos.
inline bool esteiraAutorizada(bool respostaOk, bool marcador, uint32_t idadeMs, uint32_t intervaloMs) {
  return respostaOk && marcador && (uint64_t)idadeMs <= 3ULL * (uint64_t)intervaloMs;
}

// ---- vetores do AUTO-TESTE (derivados da regra; usados no host e no boot) ----
struct VetorMarcador { const char* meta; bool esperado; };
static const VetorMarcador VET_MARCADOR[] = {
  {"esteira: ligada", true},
  {"ESTEIRA: LIGADA", true},
  {"Esteira = Ligada", true},
  {"esteira ligada", true},
  {"titulo: x\nesteira: ligada\nautor: y", true},
  {"{\"esteira\":\"ligada\"}", true},
  {"{\"esteira\": \"Ligada\", \"x\": 1}", true},
  {"esteira: ligada\r\n", true},
  {"esteira: ligada\n", true},
  {"esteira: ligada \r\n", true},
  {"esteira-ligada", true},
  {"esteira: ligada   \nx", true},
  {"esteira: ligada? nao", false},
  {"esteira: ligada -> desligada", false},
  {"esteira: ligada=false", false},
  {"esteira: ligada, depois desligada", false},  // texto puro: virgula nao fecha o valor
  {"esteira: ligada\" mas nao", false},           // aspa sem ter aberto aspas
  {"esteira: ligada} x", false},                 // chave em texto puro
  {"esteira: \"ligada\" talvez", false},          // depois da aspa de fechamento, so , } ou fim
  {"{\"esteira\":\"ligada", false},                // abriu aspas e nao fechou
  {"esteira: desligada", false},
  {"ESTEIRA: DESLIGADA", false},
  {"{\"esteira\":\"desligada\"}", false},
  {"esteira:\nligada", false},
  {"esteira: ligadas", false},
  {"esteira: ligada\nesteira: desligada", false},
  {"esteira: desligada\nesteira: ligada", false},
  {"esteira: nao ligada", false},
  {"esteiras: ligada", false},
  {"pesteira: ligada", false},
  {"ligada", false},
  {"esteira", false},
  {"", false},
  {nullptr, false},
};
struct VetorAutorizada { bool ok; bool marc; uint32_t idade; uint32_t intervalo; bool esperado; };
static const VetorAutorizada VET_AUTORIZADA[] = {
  {true, true, 0, 10000, true},
  {true, true, 30000, 10000, true},        // exatamente 3 intervalos
  {true, true, 30001, 10000, false},       // velha
  {true, true, 540000, 180000, true},
  {true, true, 540001, 180000, false},
  {false, true, 0, 10000, false},          // HTTP/TLS/parse falhou
  {true, false, 0, 10000, false},          // desligada ou sem marcador
  {true, true, 0xFFFFFFFFu, 10000, false}, // nunca houve resposta OK
  {true, true, 0xFFFFFFFFu, 0xFFFFFFFFu, true}, // sem estouro de 32 bits em 3*intervalo
};

// Roda todos os vetores; devolve quantos passaram e grava o total em *total.
inline int autoTesteEsteira(int* total) {
  int ok = 0, n = 0;
  for (const auto& v : VET_MARCADOR) { n++; if (marcadorLigada(v.meta) == v.esperado) ok++; }
  for (const auto& v : VET_AUTORIZADA) { n++; if (esteiraAutorizada(v.ok, v.marc, v.idade, v.intervalo) == v.esperado) ok++; }
  *total = n;
  return ok;
}
