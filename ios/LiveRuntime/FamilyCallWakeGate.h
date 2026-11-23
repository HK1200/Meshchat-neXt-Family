// SPDX-License-Identifier: 0BSD
#ifndef FAMILY_CALL_WAKE_GATE_H
#define FAMILY_CALL_WAKE_GATE_H
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Native-only, one-use admission after signature, consent and replay checks.
 * This is not authentication by itself. No arm/reset method is exposed to Python. */
bool family_call_wake_arm(const char *call_id, const char *voice, uint32_t seconds);
bool family_call_wake_consume(const char *voice);
void family_call_wake_cancel(const char *call_id);
void family_call_wake_reset(void);
#ifdef FAMILY_WAKE_TESTING
void family_call_wake_test_time(uint64_t milliseconds, bool available);
#endif
#ifdef __cplusplus
}
#endif
#endif
