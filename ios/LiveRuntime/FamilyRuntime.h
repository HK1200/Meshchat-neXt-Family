#ifndef FAMILY_RUNTIME_H
#define FAMILY_RUNTIME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Start once before serving requests. NULL python_home uses the default stdlib. */
bool family_runtime_start(const char *python_home, const char *modules, const char *state);

/* Returns owned UTF-8 JSON, or NULL on a bridge failure. Free with free(). */
char *family_runtime_request(const char *json);

/* Exchange bounded 48 kHz signed 16-bit mono PCM. Pass zero capacity to push only. */
size_t family_runtime_voice_exchange(const char *call_id, const uint8_t *input,
                                     size_t input_size, bool native_processing, uint8_t *output, size_t capacity);

#ifdef __cplusplus
}
#endif

#endif
