# SPDX-License-Identifier: 0BSD
"""The production native guard permits exactly one concurrent Python startup."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'ios/NextRuntimeProbe/App'


@pytest.mark.parametrize('negative', [False, True], ids=['production', 'always-enter-negative-control'])
def test_native_runtime_start_is_claimed_once_across_32_threads(tmp_path, negative):
    compiler = shutil.which('cc')
    assert compiler, 'A native C compiler is required for the runtime startup check'
    header = (APP/'NextRuntimeStartGuard.h').read_text()
    if negative:
        original = 'return !atomic_flag_test_and_set_explicit(&guard->attempted, memory_order_acq_rel);'
        assert original in header
        header = header.replace(original, 'atomic_flag_test_and_set_explicit(&guard->attempted, memory_order_acq_rel); return true;')
    (tmp_path/'NextRuntimeStartGuard.h').write_text(header)
    source = tmp_path/'startup.c'
    source.write_text(r'''
#include "NextRuntimeStartGuard.h"
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
static NextRuntimeStartGuard guard = NEXT_RUNTIME_START_GUARD_INIT;
static atomic_int ready = 0, go = 0, entered = 0;
static void *claim(void *unused) {
    (void)unused;
    atomic_fetch_add(&ready, 1);
    while (!atomic_load(&go)) sched_yield();
    if (next_runtime_claim_start(&guard)) atomic_fetch_add(&entered, 1);
    return NULL;
}
int main(void) {
    pthread_t threads[32];
    for (int i=0; i<32; ++i) if (pthread_create(&threads[i], NULL, claim, NULL)) return 2;
    while (atomic_load(&ready) != 32) sched_yield();
    atomic_store(&go, 1);
    for (int i=0; i<32; ++i) if (pthread_join(threads[i], NULL)) return 3;
    if (atomic_load(&entered) != 1) { puts("Repeated runtime initialization was admitted"); return 5; }
    for (int i=0; i<1000; ++i) if (next_runtime_claim_start(&guard)) return 6;
    puts("Exactly one runtime initialization admitted");
    return 0;
}
''')
    executable = tmp_path/'startup'
    subprocess.run([compiler, '-std=c11', '-pthread', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(executable)], check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert result.returncode == (5 if negative else 0), result.stderr + result.stdout
    assert ('Repeated' if negative else 'Exactly one') in result.stdout
    runtime = (APP/'ProbeRuntime.c').read_text()
    entry = runtime[runtime.index('void next_probe_run('):]
    assert '#include "NextRuntimeStartGuard.h"' in runtime
    assert entry.index('next_runtime_claim_start(&runtime_start_guard)') < entry.index('PyImport_AppendInittab') < entry.index('Py_InitializeFromConfig')
