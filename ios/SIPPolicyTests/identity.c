/* SPDX-License-Identifier: 0BSD */
#include "FamilySIP.h"
#include <assert.h>
int main(void) {
    assert(family_sip_call_matches("call-1", "call-1"));
    assert(!family_sip_call_matches("call-1", "call-2"));
    assert(!family_sip_call_matches("call-1", ""));
    assert(!family_sip_call_matches("", ""));
    assert(!family_sip_call_matches("call-1", 0));
    assert(family_sip_call_matches(0, "call-1"));
    return 0;
}
