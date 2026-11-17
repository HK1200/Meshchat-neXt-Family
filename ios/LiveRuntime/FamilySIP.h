#ifndef FAMILY_SIP_H
#define FAMILY_SIP_H
/* Callback strings are borrowed for the duration of the callback. */
typedef void (*FamilySIPEvent)(const char *state, const char *peer, int code);
int family_sip_run(const char *user, const char *host, int port,
                   const char *password, FamilySIPEvent callback);
void family_sip_command(int operation, const char *value);
#endif
