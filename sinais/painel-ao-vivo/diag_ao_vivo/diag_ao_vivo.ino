// VOCAID DEEP - M7: firmware de DIAGNOSTICO ao vivo (nao e o firmware da aula).
// Manda 20 linhas/s pela serial (115200) para o painel em sinais/painel-ao-vivo/:
//   L,t_ms,d2,d3,bordas_d2,bordas_d3,a0_min,a0_max,a0_med,rele_d7,led_d4,led_d5,buzzer_d6,pinos_que_mexeram
// Entradas: D2 (rpm: KY-010/KY-033) e D3 (vibracao) com INPUT_PULLUP e interrupcao CHANGE, como no firmware do M7;
//           A0 (KY-037 AO) amostrado continuamente entre as linhas.
// Saidas:   rele B (D7) ABERTO o tempo todo, exceto no teste. LEDs (D4, D5, D12, D13) acendem 200 ms a cada atividade.
// Comando:  'T' pela serial = teste das saidas por ~3 s: rele B fecha 1 s, LEDs verde/vermelho alternam, buzzer da 3 bipes.
//           SEM MOTOR LIGADO no contato do rele durante o teste.
//           'P' = 3 tons de 2 kHz no D6: separa buzzer PASSIVO (so soa com tom) de ATIVO (soa com nivel ALTO).
// Detector de pinos: vigia os pinos digitais livres (fora 0/1 da serial e as saidas 4,5,6,7,12,13) e conta mudancas
// por linha; a linha ganha um 14o campo com os pinos que mexeram ("3.22") ou "-". Acha fio no pino errado.
const byte DETECT[] = {8, 9, 10, 11, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33,
                       34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53};
const byte ND = sizeof(DETECT);
byte antDet[ND]; byte mexeu[ND];
volatile unsigned long b2 = 0, b3 = 0;
void e2() { b2++; }
void e3() { b3++; }
const int LEDS[] = {4, 5, 12, 13};
const int RELE = 7, BUZZER = 6;
unsigned long tTeste = 0;   // 0 = sem teste; senao, millis() do inicio
void setup() {
  pinMode(RELE, OUTPUT); digitalWrite(RELE, LOW);
  pinMode(BUZZER, OUTPUT); digitalWrite(BUZZER, LOW);
  for (int i = 0; i < 4; i++) { pinMode(LEDS[i], OUTPUT); digitalWrite(LEDS[i], LOW); }
  pinMode(2, INPUT_PULLUP); pinMode(3, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(2), e2, CHANGE);
  attachInterrupt(digitalPinToInterrupt(3), e3, CHANGE);
  for (byte i = 0; i < ND; i++) { pinMode(DETECT[i], INPUT_PULLUP); antDet[i] = digitalRead(DETECT[i]); mexeu[i] = 0; }
  Serial.begin(115200);
  Serial.println(F("# DIAG AO VIVO: L,t_ms,d2,d3,bordas_d2,bordas_d3,a0_min,a0_max,a0_med,rele_d7,led_d4,led_d5,buzzer_d6"));
}
// Sequencia do teste (ms desde o inicio): rele 0-1000; verde/vermelho alternam a cada 250 ms ate 2000; bipes 2000-3000.
void saidasTeste(unsigned long dt) {
  digitalWrite(RELE, dt < 1000 ? HIGH : LOW);
  bool verde = dt < 2000 && ((dt / 250) % 2 == 0);
  bool verm = dt < 2000 && !verde;
  digitalWrite(4, verde); digitalWrite(12, verde);
  digitalWrite(5, verm); digitalWrite(13, verm);
  digitalWrite(BUZZER, (dt >= 2000 && dt < 3000 && ((dt - 2000) % 330) < 150) ? HIGH : LOW);
}
void loop() {
  static unsigned long t0 = millis(), ultAtiv = 0;
  static int mn = 1023, mx = 0; static long soma = 0; static int n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'T') { tTeste = millis(); if (!tTeste) tTeste = 1; Serial.println(F("# teste das saidas")); }
    if (c == 'P' && !tTeste) { Serial.println(F("# tom de 2 kHz no D6 (buzzer passivo)")); for (int i = 0; i < 3; i++) { tone(BUZZER, 2000, 200); delay(330); } noTone(BUZZER); digitalWrite(BUZZER, LOW); }
  }
  int v = analogRead(A0);
  if (v < mn) mn = v; if (v > mx) mx = v; soma += v; n++;
  for (byte i = 0; i < ND; i++) { byte d = digitalRead(DETECT[i]); if (d != antDet[i]) { antDet[i] = d; mexeu[i] = 1; } }
  if (tTeste) {
    unsigned long dt = millis() - tTeste;
    if (dt < 3000) saidasTeste(dt);
    else { tTeste = 0; digitalWrite(RELE, LOW); digitalWrite(BUZZER, LOW); }
  }
  if (millis() - t0 >= 50) {
    t0 += 50;
    noInterrupts(); unsigned long c2 = b2, c3 = b3; b2 = 0; b3 = 0; interrupts();
    if (c2 || c3 || mx - mn > 60) ultAtiv = millis();
    if (!tTeste) { bool on = millis() - ultAtiv < 200; for (int i = 0; i < 4; i++) digitalWrite(LEDS[i], on ? HIGH : LOW); }
    Serial.print(F("L,")); Serial.print(millis()); Serial.print(',');
    Serial.print(digitalRead(2)); Serial.print(','); Serial.print(digitalRead(3)); Serial.print(',');
    Serial.print(c2); Serial.print(','); Serial.print(c3); Serial.print(',');
    Serial.print(mn); Serial.print(','); Serial.print(mx); Serial.print(','); Serial.print(n ? soma / n : 0); Serial.print(',');
    Serial.print(digitalRead(RELE)); Serial.print(','); Serial.print(digitalRead(4)); Serial.print(',');
    Serial.print(digitalRead(5)); Serial.print(','); Serial.print(digitalRead(BUZZER)); Serial.print(',');
    bool algum = false;
    for (byte i = 0; i < ND; i++) if (mexeu[i]) { if (algum) Serial.print('.'); Serial.print(DETECT[i]); algum = true; mexeu[i] = 0; }
    if (!algum) Serial.print('-');
    Serial.println();
    mn = 1023; mx = 0; soma = 0; n = 0;
  }
}
