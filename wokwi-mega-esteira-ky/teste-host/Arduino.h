// Stub de HOST do Arduino (NAO e AVR, NAO e o Wokwi) para a co-simulacao: o sketch.ino real roda contra o chip
// esteira.chip.c num relogio virtual de 50 us. As funcoes ficam em cosim.cpp; aqui so as declaracoes.
#pragma once
#include <math.h>    // sqrt
#include <stdint.h>
#include <stdio.h>

typedef uint8_t byte;
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define CHANGE 1
#define A0 54
#define A1 55
#define F(x) (x)

unsigned long micros();
unsigned long millis();
void delay(unsigned long ms);               // avanca o relogio virtual (o chip continua rodando)
int analogRead(int pino);                   // A0 = tensao do pin_dac_write do chip SOM, ADC de 10 bits em 5 V
int digitalRead(int pino);                  // D2 = OPT, D3 = VIB do chip
void digitalWrite(int pino, int nivel);     // D7 = IN do rele B -> PWR do chip (em serie com a chave do rele A)
void pinMode(int pino, int modo);
void noInterrupts();
void interrupts();
inline int digitalPinToInterrupt(int p) { return p; }   // no host o "numero da interrupcao" e o proprio pino
void attachInterrupt(int interrupcao, void (*isr)(), int modo);   // so CHANGE

void cs_serial(const char *s);              // stdout + leitor de linhas da co-simulacao

struct SerialStub {
  void begin(long) {}
  void print(const char *s) { cs_serial(s); }
  void print(char c) { char b[2] = {c, 0}; cs_serial(b); }
  void print(float v, int d = 2) { char b[32]; snprintf(b, sizeof b, "%.*f", d, v); cs_serial(b); }
  void print(unsigned long v) { char b[24]; snprintf(b, sizeof b, "%lu", v); cs_serial(b); }
  void print(long v) { char b[24]; snprintf(b, sizeof b, "%ld", v); cs_serial(b); }
  void print(unsigned int v) { char b[24]; snprintf(b, sizeof b, "%u", v); cs_serial(b); }
  void print(int v) { char b[24]; snprintf(b, sizeof b, "%d", v); cs_serial(b); }
  void println() { cs_serial("\n"); }
  template <typename T> void println(T v) { print(v); println(); }
  void println(float v, int d) { print(v, d); println(); }
};
static SerialStub Serial;
