//
// Created by henry on 5/25/24.
//

#ifndef RP2040_IO_H
#define RP2040_IO_H

#include "cobs.h"
#include "pico/stdlib.h"
#include <memory.h>
#include <stdio.h>

#define MUT_BUF_LEN 50


typedef struct ServoDegreesMutation {
  char rightFront[3];
  char leftFront[3];
  char rightBack[3];
  char leftBack[3];
} ServoDegreesMutation;

cobs_decode_status send(uint id, uint8_t src_buf[], size_t src_len) {
  size_t msg_len = src_len + 1;
  uint8_t msg_buf[msg_len];
  msg_buf[0] = id;
  memcpy(&msg_buf[1], src_buf, src_len);

  size_t dst_len = COBS_ENCODE_DST_BUF_LEN_MAX(msg_len);
  uint8_t dst_buf[dst_len + 1];
  cobs_encode_result result =
      cobs_encode(dst_buf, dst_len, msg_buf, msg_len);

  if (result.status != COBS_DECODE_OK) {
    return result.status;
  }
  dst_buf[result.out_len] = 0;
  for (int i = 0; i <= result.out_len; ++i) {
    putchar_raw(dst_buf[i]);
  }
  return result.status;
}

void sendState(uint8_t state[5]) { send(0, state, 5); }

void sendBytes(uint8_t bytes[], size_t len) { send(1, bytes, len); }

void sendString(const char str[]) {send(2, (uint8_t *)str, strlen(str));}

void processCommands(ServoDegreesMutation* sd_mut){
  static uint8_t state[5] = {0, 1, 0, 0, 1};
  static uint8_t mutation_buf[MUT_BUF_LEN];
  static uint8_t decode_buf[MUT_BUF_LEN];
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
  case 0:
    sendBytes(mutation_buf, 13);
    sendString("hello world");
    for (int i = 0; i < 3; ++i) {
      sd_mut->rightFront[i] = mutation_buf[i + 1];
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut->leftFront[i] = mutation_buf[i + 3 + 1];
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut->rightBack[i] = mutation_buf[i + 6 + 1];
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut->leftBack[i] = mutation_buf[i + 9 + 1];
    }
    break;
  case 1:
    sendState(state);
    break;
  }
  mutation_buf[0] = 0xFF;
}
#endif // RP2040_IO_H
