/* SPDX-License-Identifier: 0BSD */
#include "FamilySIP.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static bool registered, seen_call, ended, failed;
static const char *mode;
static char target[128];
static void received(const char *state, const char *peer, int code) {
    (void)peer; (void)code;
    if (!strcmp(state, "registered") && !registered) {
        registered = true;
        if (!strcmp(mode, "outgoing")) family_sip_command(1, target);
    } else if (!strcmp(state, "incoming") && !strcmp(mode, "incoming")) {
        seen_call = true;
        family_sip_command(3, NULL);
    } else if (!strcmp(state, "calling") && !strcmp(mode, "outgoing")) {
        seen_call = true;
    } else if (!strcmp(state, "ended")) {
        ended = true;
        family_sip_command(9, NULL);
    } else if (!strcmp(state, "command_failed") || !strcmp(state, "engine_failed") || !strcmp(state, "audio_error")) {
        failed = true;
        family_sip_command(9, NULL);
    }
}
int main(int argc, char **argv) {
    if (argc != 5) return 2;
    mode = argv[4];
    if (strcmp(mode, "incoming") && strcmp(mode, "outgoing")) return 2;
    snprintf(target, sizeof(target), "sip:private-peer@127.0.0.1:%d", atoi(argv[2]));
    alarm(45);
    int result = family_sip_run(argv[1], "127.0.0.1", atoi(argv[2]), argv[3], received);
    if (result || !registered || !seen_call || !ended || failed) {
        fprintf(stderr, "SIP %s signaling failed (%d, registered=%d, call=%d, ended=%d, failed=%d)\n", mode, result, registered, seen_call, ended, failed);
        return 1;
    }
    puts("Native SIP call signaling and shutdown passed");
    return 0;
}
