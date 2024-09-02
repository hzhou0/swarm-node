//
// Created by henry on 5/25/24.
//

#ifndef RP2040_COBS_H
#define RP2040_COBS_H
#include "stdlib.h"
#include "stdint.h"

/*****************************************************************************
 * Defines
 ****************************************************************************/

#define COBS_ENCODE_DST_BUF_LEN_MAX(SRC_LEN)            (((SRC_LEN) == 0u) ? 1u : ((SRC_LEN) + (((SRC_LEN) + 253u) / 254u)))
#define COBS_DECODE_DST_BUF_LEN_MAX(SRC_LEN)            (((SRC_LEN) == 0u) ? 0u : ((SRC_LEN) - 1u))

/*
 * For in-place encoding, the source data must be offset in the buffer by
 * the following amount (or more).
 */
#define COBS_ENCODE_SRC_OFFSET(SRC_LEN)                 (((SRC_LEN) + 253u)/254u)


/*****************************************************************************
 * Typedefs
 ****************************************************************************/

typedef enum
{
  COBS_ENCODE_OK                  = 0x00,
  COBS_ENCODE_NULL_POINTER        = 0x01,
  COBS_ENCODE_OUT_BUFFER_OVERFLOW = 0x02
} cobs_encode_status;

typedef struct
{
  size_t              out_len;
  int status;
} cobs_encode_result;


typedef enum
{
  COBS_DECODE_OK                  = 0x00,
  COBS_DECODE_NULL_POINTER        = 0x01,
  COBS_DECODE_OUT_BUFFER_OVERFLOW = 0x02,
  COBS_DECODE_ZERO_BYTE_IN_INPUT  = 0x04,
  COBS_DECODE_INPUT_TOO_SHORT     = 0x08
} cobs_decode_status;

typedef struct
{
  size_t              out_len;
  int status;
} cobs_decode_result;


/*****************************************************************************
 * Functions
 ****************************************************************************/

/* COBS-encode a string of input bytes.
 *
 * dst_buf_ptr:    The buffer into which the result will be written
 * dst_buf_len:    Length of the buffer into which the result will be written
 * src_ptr:        The byte string to be encoded
 * src_len         Length of the byte string to be encoded
 *
 * returns:        A struct containing the success status of the encoding
 *                 operation and the length of the result (that was written to
 *                 dst_buf_ptr)
 */
cobs_encode_result cobs_encode(uint8_t *dst_buf_ptr, size_t dst_buf_len,
                               const uint8_t *src_ptr, size_t src_len) {
  cobs_encode_result result = {0u, COBS_ENCODE_OK};
  const uint8_t *src_read_ptr = src_ptr;
  const uint8_t *src_end_ptr = src_read_ptr + src_len;
  uint8_t *dst_buf_start_ptr = dst_buf_ptr;
  uint8_t *dst_buf_end_ptr = dst_buf_start_ptr + dst_buf_len;
  uint8_t *dst_code_write_ptr = dst_buf_ptr;
  uint8_t *dst_write_ptr = dst_code_write_ptr + 1u;
  uint8_t src_byte = 0u;
  uint8_t search_len = 1u;

  /* First, do a NULL pointer check and return immediately if it fails. */
  if ((dst_buf_ptr == NULL) || (src_ptr == NULL)) {
    result.status = COBS_ENCODE_NULL_POINTER;
    return result;
  }

  if (src_len != 0u) {
    /* Iterate over the source bytes */
    for (;;) {
      /* Check for running out of output buffer space */
      if (dst_write_ptr >= dst_buf_end_ptr) {
        result.status |= COBS_ENCODE_OUT_BUFFER_OVERFLOW;
        break;
      }

      src_byte = *src_read_ptr++;
      if (src_byte == 0u) {
        /* We found a zero byte */
        *dst_code_write_ptr = search_len;
        dst_code_write_ptr = dst_write_ptr++;
        search_len = 1u;
        if (src_read_ptr >= src_end_ptr) {
          break;
        }
      } else {
        /* Copy the non-zero byte to the destination buffer */
        *dst_write_ptr++ = src_byte;
        search_len++;
        if (src_read_ptr >= src_end_ptr) {
          break;
        }
        if (search_len == 0xFFu) {
          /* We have a long string of non-zero bytes, so we need
           * to write out a length code of 0xFF. */
          *dst_code_write_ptr = search_len;
          dst_code_write_ptr = dst_write_ptr++;
          search_len = 1u;
        }
      }
    }
  }

  /* We've reached the end of the source data (or possibly run out of output
   * buffer) Finalise the remaining output. In particular, write the code
   * (length) byte. Update the pointer to calculate the final output length.
   */
  if (dst_code_write_ptr >= dst_buf_end_ptr) {
    /* We've run out of output buffer to write the code byte. */
    result.status |= COBS_ENCODE_OUT_BUFFER_OVERFLOW;
    dst_write_ptr = dst_buf_end_ptr;
  } else {
    /* Write the last code (length) byte. */
    *dst_code_write_ptr = search_len;
  }

  /* Calculate the output length, from the value of dst_code_write_ptr */
  result.out_len = (size_t)(dst_write_ptr - dst_buf_start_ptr);

  return result;
}

/* Decode a COBS byte string.
 *
 * dst_buf_ptr:    The buffer into which the result will be written
 * dst_buf_len:    Length of the buffer into which the result will be written
 * src_ptr:        The byte string to be decoded
 * src_len         Length of the byte string to be decoded
 *
 * returns:        A struct containing the success status of the decoding
 *                 operation and the length of the result (that was written to
 *                 dst_buf_ptr)
 */
cobs_decode_result cobs_decode(uint8_t *dst_buf_ptr, size_t dst_buf_len,
                               const uint8_t *src_ptr, size_t src_len) {
  cobs_decode_result result = {0u, COBS_DECODE_OK};
  const uint8_t *src_read_ptr = src_ptr;
  const uint8_t *src_end_ptr = src_read_ptr + src_len;
  uint8_t *dst_buf_start_ptr = dst_buf_ptr;
  uint8_t *dst_buf_end_ptr = dst_buf_start_ptr + dst_buf_len;
  uint8_t *dst_write_ptr = dst_buf_ptr;
  size_t remaining_bytes;
  uint8_t src_byte;
  uint8_t i;
  uint8_t len_code;

  /* First, do a NULL pointer check and return immediately if it fails. */
  if ((dst_buf_ptr == NULL) || (src_ptr == NULL)) {
    result.status = COBS_DECODE_NULL_POINTER;
    return result;
  }

  if (src_len != 0u) {
    for (;;) {
      len_code = *src_read_ptr++;
      if (len_code == 0u) {
        result.status |= COBS_DECODE_ZERO_BYTE_IN_INPUT;
        break;
      }
      len_code--;

      /* Check length code against remaining input bytes */
      remaining_bytes = (size_t)(src_end_ptr - src_read_ptr);
      if (len_code > remaining_bytes) {
        result.status |= COBS_DECODE_INPUT_TOO_SHORT;
        len_code = (uint8_t)remaining_bytes;
      }

      /* Check length code against remaining output buffer space */
      remaining_bytes = (size_t)(dst_buf_end_ptr - dst_write_ptr);
      if (len_code > remaining_bytes) {
        result.status |= COBS_DECODE_OUT_BUFFER_OVERFLOW;
        len_code = (uint8_t)remaining_bytes;
      }

      for (i = len_code; i != 0u; i--) {
        src_byte = *src_read_ptr++;
        if (src_byte == 0u) {
          result.status |= COBS_DECODE_ZERO_BYTE_IN_INPUT;
        }
        *dst_write_ptr++ = src_byte;
      }

      if (src_read_ptr >= src_end_ptr) {
        break;
      }

      /* Add a zero to the end */
      if (len_code != 0xFEu) {
        if (dst_write_ptr >= dst_buf_end_ptr) {
          result.status |= COBS_DECODE_OUT_BUFFER_OVERFLOW;
          break;
        }
        *dst_write_ptr++ = '\0';
      }
    }
  }

  result.out_len = (size_t)(dst_write_ptr - dst_buf_start_ptr);

  return result;
}
#endif // RP2040_COBS_H
