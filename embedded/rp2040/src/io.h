#pragma once
#include "cobs.h"
#include "pico/stdlib.h"
#include <memory.h>
#include <stdarg.h>
#include <stdio.h>

#ifndef __STDC_IEC_559__
#ifndef PICO_RP2040
#error "Requires IEEE 754 floating point (RP2040 is IEEE754 compliant in reprsentation)"
#endif
#endif

#define MUT_BUF_LEN 100

inline char *append_uint8(char *string, uint8_t input) {
  string[0] = input;
  return &string[1];
}

inline char *append_uint16(char *string, uint32_t input) {
  string[0] = (input >> 8) & 0xFF;
  string[1] = input & 0xFF;
  return &string[2];
}

inline char *append_uint32(char *string, uint32_t input) {
  string[0] = (input >> 24) & 0xFF;
  string[1] = (input >> 16) & 0xFF;
  string[2] = (input >> 8) & 0xFF;
  string[3] = input & 0xFF;
  return &string[4];
}

inline char *append_uint64(char *string, uint64_t input) {
  for (int i = 0; i < 8; ++i) {
    string[i] = (input >> (64 - 8 * (i + 1))) & 0xFF;
  }
  return &string[8];
}

inline char *append_int32(char *string, int32_t input) {
  string[0] = (input >> 24) & 0xFF;
  string[1] = (input >> 16) & 0xFF;
  string[2] = (input >> 8) & 0xFF;
  string[3] = input & 0xFF;
  return &string[4];
}

inline char *append_float(char *string, float input) {
  memcpy(string, &input, sizeof(float));
  return &string[sizeof(float)];
}

inline char *append_double(char *string, double input) {
  memcpy(string, &input, sizeof(double));
  return &string[sizeof(double)];
}

inline int16_t bytesToInt(const uint8_t msb, const uint8_t lsb) {
  uint16_t raw = (uint16_t)(msb << 8) | lsb;
  const int16_t reinterpret = *(int16_t *)&raw;
  return reinterpret;
}

enum event {
  EVENT_STATE = 0,
  EVENT_PRINT_BYTES = 1,
  EVENT_PRINT_STRING = 2,
  EVENT_LOG = 3,
  EVENT_INA226_STATE = 4,
  EVENT_GPI_STATE = 5,
  EVENT_MPU6500_STATE = 6,
  EMIT_MAIN_LOOP_PERF = 7
};

static inline cobs_decode_status emit(enum event id, const uint8_t src_buf[], size_t src_len) {
  const size_t msg_len = src_len + 1;
  uint8_t msg_buf[msg_len];
  msg_buf[0] = (uint8_t)id;
  memcpy(&msg_buf[1], src_buf, src_len);

  const size_t dst_len = COBS_ENCODE_DST_BUF_LEN_MAX(msg_len);
  uint8_t dst_buf[dst_len];
  const cobs_encode_result result = cobs_encode(dst_buf, dst_len, msg_buf, msg_len);

  if (result.status != COBS_DECODE_OK) {
    return result.status;
  }
  putchar_raw(0);
  for (int i = 0; i < result.out_len; ++i) {
    putchar_raw(dst_buf[i]);
  }
  putchar_raw(0);
  return result.status;
}

inline static void emit_bytes(uint8_t bytes[], size_t len) { emit(EVENT_PRINT_BYTES, bytes, len); }

inline static void emit_string(const char str[]) {
  emit(EVENT_PRINT_STRING, (uint8_t *)str, strlen(str));
}

// Python compatible log levels
enum LOG_LEVEL {
  LOG_LEVEL_CRITICAL = 50,
  LOG_LEVEL_ERROR = 40,
  LOG_LEVEL_WARN = 30,
  LOG_LEVEL_INFO = 20,
  LOG_LEVEL_DEBUG = 10,
};

#define STRIPPATH(s)                                                                               \
  (sizeof(s) > 2 && (s)[sizeof(s) - 2] == '/'     ? (s) + sizeof(s) - 1                            \
   : sizeof(s) > 3 && (s)[sizeof(s) - 3] == '/'   ? (s) + sizeof(s) - 2                            \
   : sizeof(s) > 4 && (s)[sizeof(s) - 4] == '/'   ? (s) + sizeof(s) - 3                            \
   : sizeof(s) > 5 && (s)[sizeof(s) - 5] == '/'   ? (s) + sizeof(s) - 4                            \
   : sizeof(s) > 6 && (s)[sizeof(s) - 6] == '/'   ? (s) + sizeof(s) - 5                            \
   : sizeof(s) > 7 && (s)[sizeof(s) - 7] == '/'   ? (s) + sizeof(s) - 6                            \
   : sizeof(s) > 8 && (s)[sizeof(s) - 8] == '/'   ? (s) + sizeof(s) - 7                            \
   : sizeof(s) > 9 && (s)[sizeof(s) - 9] == '/'   ? (s) + sizeof(s) - 8                            \
   : sizeof(s) > 10 && (s)[sizeof(s) - 10] == '/' ? (s) + sizeof(s) - 9                            \
   : sizeof(s) > 11 && (s)[sizeof(s) - 11] == '/' ? (s) + sizeof(s) - 10                           \
                                                  : (s))

#define __FILENAME__ STRIPPATH(__FILE__)

#define log_debug(...) emit_log(LOG_LEVEL_DEBUG, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_info(...) emit_log(LOG_LEVEL_INFO, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_warn(...) emit_log(LOG_LEVEL_WARN, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_error(...) emit_log(LOG_LEVEL_ERROR, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_critical(...) emit_log(LOG_LEVEL_CRITICAL, __FILENAME__, __LINE__, __VA_ARGS__)

char error_log_buf[100];
uint error_log_len = 0;
enum LOG_LEVEL log_level = LOG_LEVEL_INFO;

static void emit_log(const uint8_t lvl, const char *file, const uint32_t line, const char *fmt,
                     ...) {
  if (lvl < log_level) {
    return;
  }
  char log_buf[100];
  uint i = 0;
  strcpy(&log_buf[i], file);
  i += strlen(file);
  log_buf[++i] = '\0';
  append_uint8(&log_buf[i], lvl);
  i += 1;
  append_uint32(&log_buf[i], line);
  i += 4;
  va_list args;
  va_start(args, fmt);
  char msg_buf[100 - i];
  vsprintf(msg_buf, fmt, args);
  for (int j = 0; j < strlen(msg_buf); ++j) {
    log_buf[i] = msg_buf[j];
    i++;
  }
  va_end(args);
  emit(EVENT_LOG, (uint8_t *)log_buf, i);
  if (lvl >= LOG_LEVEL_ERROR) {
    memcpy(error_log_buf, log_buf, i);
    error_log_len = i;
  }
}

inline static void emit_buffered_error() {
  if (error_log_len != 0) {
    emit(EVENT_LOG, (uint8_t *)error_log_buf, error_log_len);
    error_log_len = 0;
  } else {
    log_info("No buffered errors found");
  }
}

enum mutation {
  MUTATION_SERVO_DEGREES = 0,
  MUTATION_REQUEST_STATE = 1,
  MUTATION_MPU6500_CALIBRATE = 2,
  MUTATION_EMIT_BUFFERED_ERROR_LOG = 3,
  MUTATION_MPU6500_RESET_ODOM = 4,
  MUTATION_SET_PROGRAM_OPTIONS = 5
};

typedef struct ServoDegreesMutation {
  char right_front[3];
  char right_back[3];
  char left_front[3];
  char left_back[3];
} ServoDegreesMutation;

typedef struct MainLoopPerf {
  uint16_t idle_loops_per_10000;
  uint64_t us_per_10000;
} MainLoopPerf;

inline static void emit_idle_loops_count_per_10000(const MainLoopPerf perf) {
  const uint buf_len = sizeof(uint16_t) + sizeof(uint32_t);
  uint8_t buffer[buf_len];
  char *cursor = append_uint16((char *)buffer, perf.idle_loops_per_10000);
  append_uint32(cursor, (uint32_t)perf.us_per_10000);
  emit(EMIT_MAIN_LOOP_PERF, buffer, buf_len);
}