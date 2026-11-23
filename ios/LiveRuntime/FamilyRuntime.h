#ifndef FAMILY_RUNTIME_H
#define FAMILY_RUNTIME_H

#include "FamilySIP.h"
#include "FamilyCallWakeGate.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Install before starting Python. Called only by a background hint sender. */
typedef int32_t (*FamilyHTTPSPost)(const char *url, const uint8_t *body, size_t length);
void family_runtime_set_https_post(FamilyHTTPSPost post);

/* JSON radio operations return owned UTF-8 JSON, freed by the bridge. */
typedef char *(*FamilyBluetoothRequest)(const char *request);
void family_runtime_set_bluetooth(FamilyBluetoothRequest request);

/* Payload-free inbox change notification. Install before starting Python. */
typedef void (*FamilyInboxChanged)(void);
void family_runtime_set_inbox_changed(FamilyInboxChanged callback);

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
