/* SPDX-License-Identifier: 0BSD */
#include "FamilySIP.h"
#include <string.h>
bool family_sip_call_matches(const char *expected, const char *active) {
    if (!expected) return true; /* Compatibility for engine-level shutdown/tests. */
    return active && expected[0] && active[0] && !strcmp(expected, active);
}
