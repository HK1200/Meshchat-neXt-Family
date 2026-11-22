void next_probe_run(const char *home, const char *modules, const char *ready_file);

typedef char *(*NextBluetoothRequest)(const char *);
void next_probe_set_bluetooth(NextBluetoothRequest request);

void next_probe_set_credentials(NextBluetoothRequest request);

#include "FamilySIP.h"
void next_probe_set_sip(NextBluetoothRequest request);

void next_probe_request_listener_recovery(void);
unsigned long next_probe_listener_generation(void);

/* Caller frees the returned synthetic test report; NULL means not ready. */
char *next_probe_check_voice_codecs(void);

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
void next_probe_set_voice(NextBluetoothRequest request);
size_t family_runtime_voice_exchange(const char *call_id, const uint8_t *input,
                                     size_t input_size, bool native_processing,
                                     uint8_t *output, size_t capacity);

void next_probe_set_voice_muted(bool muted);

/* Used only by bounded signed-hint worker threads, never the main/audio queue. */
typedef int32_t (*NextHTTPSPost)(const char *, const uint8_t *, size_t);
void next_probe_set_https_post(NextHTTPSPost post);
