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
