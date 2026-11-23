/* SPDX-License-Identifier: 0BSD */
#ifndef NEXT_RUNTIME_START_GUARD_H
#define NEXT_RUNTIME_START_GUARD_H
#include <stdbool.h>
#include <stdatomic.h>

typedef struct { atomic_flag attempted; } NextRuntimeStartGuard;
#define NEXT_RUNTIME_START_GUARD_INIT { ATOMIC_FLAG_INIT }

/* Never reset after failure: CPython may already be partially initialized. */
static inline bool next_runtime_claim_start(NextRuntimeStartGuard *guard) {
    return !atomic_flag_test_and_set_explicit(&guard->attempted, memory_order_acq_rel);
}
#endif
