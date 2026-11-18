#ifndef FAMILY_SIP_H
#define FAMILY_SIP_H
#include <stdbool.h>
/* Callback strings are borrowed for the duration of the callback. */
typedef void (*FamilySIPEvent)(const char *state, const char *peer, int code, const char *call_id);
int family_sip_run(const char *user, const char *host, int port,
                   const char *password, FamilySIPEvent callback);
void family_sip_command(int operation, const char *value);
/* Call controls carry the exact transport call ID; stale controls are ignored. */
int family_sip_call_command(int operation, const char *value, const char *call_id);
bool family_sip_call_matches(const char *expected, const char *active);
#endif
