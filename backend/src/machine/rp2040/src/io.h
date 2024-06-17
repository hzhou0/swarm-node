#pragma once
#include "cobs.h"
#include "gpi.h"
#include "pico/stdlib.h"
#include <memory.h>
#include <stdarg.h>
#include <stdio.h>

#define MUT_BUF_LEN 100

typedef struct ServoDegreesMutation {
  char right_front[3];
  char right_back[3];
  char left_front[3];
  char left_back[3];
} ServoDegreesMutation;

typedef struct State {
  GPI gpi;
  INA226State current_sensor;
} State;

enum event {
  EVENT_STATE = 0,
  EVENT_PRINT_BYTES = 1,
  EVENT_PRINT_STRING = 2,
  EVENT_LOG = 3
};

cobs_decode_status emit(enum event id, const uint8_t src_buf[],
                        size_t src_len) {
  size_t msg_len = src_len + 1;
  uint8_t msg_buf[msg_len];
  msg_buf[0] = id;
  memcpy(&msg_buf[1], src_buf, src_len);

  size_t dst_len = COBS_ENCODE_DST_BUF_LEN_MAX(msg_len);
  uint8_t dst_buf[dst_len + 1];
  cobs_encode_result result = cobs_encode(dst_buf, dst_len, msg_buf, msg_len);

  if (result.status != COBS_DECODE_OK) {
    return result.status;
  }
  dst_buf[result.out_len] = 0;
  for (int i = 0; i <= result.out_len; ++i) {
    putchar_raw(dst_buf[i]);
  }
  return result.status;
}

void emit_state(const State *state) {
  const uint8_t stateBuf[sizeof(State)] = {
      state->gpi.charged1, state->gpi.charged2, state->gpi.charged3,
      state->gpi.charged4, state->gpi.in_conn,
  };
  emit(EVENT_STATE, stateBuf, sizeof(State));
}

void emit_bytes(uint8_t bytes[], size_t len) {
  emit(EVENT_PRINT_BYTES, bytes, len);
}

void emit_string(const char str[]) {
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

void append_uint8(char *string, uint8_t input) {
  string[0] = input;
}

void append_uint32(char *string, uint32_t input) {
  string[0] = (input >> 24) & 0xFF;
  string[1] = (input >> 16) & 0xFF;
  string[2] = (input >> 8) & 0xFF;
  string[3] = input & 0xFF;
}

#define STRIPPATH(s)\
    (sizeof(s) > 2 && (s)[sizeof(s)-2] == '/' ? (s) + sizeof(s) - 1 : \
    sizeof(s) > 3 && (s)[sizeof(s)-3] == '/' ? (s) + sizeof(s) - 2 : \
    sizeof(s) > 4 && (s)[sizeof(s)-4] == '/' ? (s) + sizeof(s) - 3 : \
    sizeof(s) > 5 && (s)[sizeof(s)-5] == '/' ? (s) + sizeof(s) - 4 : \
    sizeof(s) > 6 && (s)[sizeof(s)-6] == '/' ? (s) + sizeof(s) - 5 : \
    sizeof(s) > 7 && (s)[sizeof(s)-7] == '/' ? (s) + sizeof(s) - 6 : \
    sizeof(s) > 8 && (s)[sizeof(s)-8] == '/' ? (s) + sizeof(s) - 7 : \
    sizeof(s) > 9 && (s)[sizeof(s)-9] == '/' ? (s) + sizeof(s) - 8 : \
    sizeof(s) > 10 && (s)[sizeof(s)-10] == '/' ? (s) + sizeof(s) - 9 : \
    sizeof(s) > 11 && (s)[sizeof(s)-11] == '/' ? (s) + sizeof(s) - 10 : (s))

#define __FILENAME__ STRIPPATH(__FILE__)


#define log_debug(...)                                                         \
  emit_log(LOG_LEVEL_DEBUG, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_info(...) emit_log(LOG_LEVEL_INFO, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_warn(...) emit_log(LOG_LEVEL_WARN, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_error(...)                                                         \
  emit_log(LOG_LEVEL_ERROR, __FILENAME__, __LINE__, __VA_ARGS__)
#define log_critical(...)                                                      \
  emit_log(LOG_LEVEL_CRITICAL, __FILENAME__, __LINE__, __VA_ARGS__)
void emit_log(uint8_t lvl, const char *file, uint32_t line, const char *fmt,
              ...) {
  char log_buf[100];
  uint i = 0;
  strcpy(&log_buf[i], file);
  i += strlen(file);
  log_buf[++i]='\0';
  append_uint8(&log_buf[i], lvl);
  i += 1;
  append_uint32(&log_buf[i], line);
  i += 4;
  va_list args;
  va_start(args, fmt);
  char msg_buf[100-i];
  vsprintf(msg_buf, fmt, args);
  for (int j = 0; j < strlen(msg_buf); ++j) {
    log_buf[i]=msg_buf[j];
    i++;
  }
  va_end(args);
  emit(EVENT_LOG, (uint8_t *)log_buf, i);
}

enum mutation {
  MUTATION_SERVO_DEGREES = 0,
  MUTATION_REQUEST_STATE = 1,
};

void process_commands(ServoDegreesMutation *sd_mut, const State *state) {
  uint8_t mutation_buf[MUT_BUF_LEN];
  uint8_t decode_buf[MUT_BUF_LEN];
  int c = getchar_timeout_us(0);
  if (c == PICO_ERROR_TIMEOUT || c == 0) {
    return;
  } else {
    decode_buf[0] = c;
    uint decode_len = 1;
    for (int i = 1; i < MUT_BUF_LEN; ++i) {
      c = getchar_timeout_us(0);
      if (c == 0) {
        decode_len = i;
        break;
      } else {
        decode_buf[i] = c;
      }
    }
    cobs_decode_result res =
        cobs_decode(mutation_buf, MUT_BUF_LEN, decode_buf, decode_len);
    if (res.status != COBS_DECODE_OK) {
      mutation_buf[0] = 0xFF;
      return;
    }
  }

  switch (mutation_buf[0]) {
  case MUTATION_SERVO_DEGREES:
    emit_bytes(mutation_buf, 13);
    for (int i = 0; i < 3; ++i) {
      sd_mut->right_front[i] = mutation_buf[i + 1];
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut->right_back[i] = mutation_buf[i + 6 + 1];
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut->left_front[i] = mutation_buf[i + 3 + 1];
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut->left_back[i] = mutation_buf[i + 9 + 1];
    }
    break;
  case MUTATION_REQUEST_STATE:
    emit_state(state);
    break;
  }
  mutation_buf[0] = 0xFF;
}
