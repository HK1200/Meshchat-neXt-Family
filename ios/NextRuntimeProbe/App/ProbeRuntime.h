void next_probe_run(const char *home, const char *modules, const char *ready_file);

typedef char *(*NextBluetoothRequest)(const char *);
void next_probe_set_bluetooth(NextBluetoothRequest request);

void next_probe_set_credentials(NextBluetoothRequest request);

#include "FamilySIP.h"
void next_probe_set_sip(NextBluetoothRequest request);
