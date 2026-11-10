// stub minimo de HOST (NAO e AVR) para rodar o .ino real no computador
#pragma once
#include <stdio.h>
#include <math.h>
#include <string.h>
#include <stdint.h>
typedef uint8_t byte;
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define CHANGE 1
#define A0 54
#define A1 55
#define F(x) (x)
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline int digitalRead(int) { return 1; }
inline int analogRead(int) { return 512; }
inline unsigned long millis() { return 0; }
inline unsigned long micros() { return 0; }
inline void delay(unsigned long) {}
inline void noInterrupts() {}
inline void interrupts() {}
inline int digitalPinToInterrupt(int p) { return p; }
inline void attachInterrupt(int, void (*)(), int) {}
struct SerialStub {
  void begin(long) {}
  void print(const char* s) { fputs(s, stdout); }
  void print(float v, int d = 2) { printf("%.*f", d, v); }
  void print(unsigned long v) { printf("%lu", v); }
  void print(long v) { printf("%ld", v); }
  void print(unsigned int v) { printf("%u", v); }
  void print(int v) { printf("%d", v); }
  void print(char c) { putchar(c); }
  void println() { putchar('\n'); }
  void println(const char* s) { puts(s); }
  void println(float v, int d = 2) { printf("%.*f\n", d, v); }
  void println(unsigned long v) { printf("%lu\n", v); }
  void println(long v) { printf("%ld\n", v); }
  void println(unsigned int v) { printf("%u\n", v); }
  void println(int v) { printf("%d\n", v); }
};
static SerialStub Serial;
