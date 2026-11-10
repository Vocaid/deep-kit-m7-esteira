// Teste de HOST da logica pura (../logica.h). Nao e ESP8266.
#include <stdio.h>
#include "../logica.h"
int main() {
  int total = 0;
  int ok = autoTesteEsteira(&total);
  printf("AUTO-TESTE: %d/%d -> %s\n", ok, total, ok == total ? "PASS" : "FAIL");
  return ok == total ? 0 : 1;
}
