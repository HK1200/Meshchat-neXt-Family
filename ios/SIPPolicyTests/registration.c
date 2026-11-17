/* SPDX-License-Identifier: 0BSD */
#include "FamilySIP.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static bool registered;
static void received(const char *state, const char *peer, int code) {
    (void)peer; (void)code;
    if (!strcmp(state, "registered") && !registered) {
        registered = true;
        family_sip_command(9, NULL);
    }
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    alarm(40);
    int result = family_sip_run(argv[1], "127.0.0.1", atoi(argv[2]), argv[3], received);
    if (result || !registered) {
        fprintf(stderr, "SIP registration failed (%d)\n", result);
        return 1;
    }
    puts("Native SIP digest registration and shutdown passed");
    return 0;
}
