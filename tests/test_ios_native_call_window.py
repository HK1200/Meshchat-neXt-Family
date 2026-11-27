"""Exercise the actual native-only wake gate, including parallel consumption."""
import ctypes
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_window_expiry_binding_reset_and_one_use_under_contention(tmp_path):
    harness = tmp_path / "window.c"
    harness.write_text(r'''#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include "FamilyCallWakeGate.h"
static const char *call="0123456789abcdef0123456789abcdef";
static const char *other="123456789abcdef0123456789abcdef0";
static const char *voice="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static atomic_int accepted;
static void *consume(void *unused) {
    (void)unused;
    if (family_call_wake_consume(voice)) atomic_fetch_add(&accepted,1);
    return 0;
}
int main(void) {
    family_call_wake_test_time(1000,true);
    assert(!family_call_wake_consume(voice));
    assert(!family_call_wake_arm(0,voice,30));
    assert(!family_call_wake_arm("short",voice,30));
    assert(!family_call_wake_arm(call,"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",30));
    assert(!family_call_wake_arm(call,voice,0));
    assert(!family_call_wake_arm(call,voice,31));
    assert(family_call_wake_arm(call,voice,30));
    assert(!family_call_wake_arm(call,voice,30)); /* No lifetime extension. */
    assert(!family_call_wake_arm(other,voice,30)); /* Do not replace a live call. */
    assert(!family_call_wake_consume(other));
    family_call_wake_cancel(other); /* A stale cancel cannot end this call. */
    assert(family_call_wake_consume(voice));
    assert(!family_call_wake_consume(voice));
    assert(family_call_wake_arm(call,voice,30));
    family_call_wake_test_time(31000,true);
    assert(!family_call_wake_consume(voice)); /* Expiry is exclusive. */
    family_call_wake_test_time(1000,true);
    assert(family_call_wake_arm(call,voice,1));
    family_call_wake_test_time(1999,true);assert(family_call_wake_consume(voice));
    assert(family_call_wake_arm(call,voice,1));
    family_call_wake_test_time(1998,true);assert(!family_call_wake_consume(voice));
    assert(family_call_wake_arm(call,voice,1));
    family_call_wake_cancel(call);assert(!family_call_wake_consume(voice));
    assert(family_call_wake_arm(call,voice,1));
    family_call_wake_reset();assert(!family_call_wake_consume(voice));
    family_call_wake_test_time(UINT64_MAX-500,true);
    assert(!family_call_wake_arm(call,voice,1));
    family_call_wake_test_time(1000,false);
    assert(!family_call_wake_arm(call,voice,1));
    family_call_wake_test_time(1000,true);
    assert(family_call_wake_arm(call,voice,1));
    family_call_wake_test_time(1000,false);assert(!family_call_wake_consume(voice));
    family_call_wake_test_time(1000,true);assert(!family_call_wake_consume(voice));
    assert(family_call_wake_arm(call,voice,30));
    pthread_t threads[8];
    for(int i=0;i<8;i++)assert(pthread_create(&threads[i],0,consume,0)==0);
    for(int i=0;i<8;i++)assert(pthread_join(threads[i],0)==0);
    assert(atomic_load(&accepted)==1);
    return 0;
}
''')
    binary = tmp_path / "window"
    folder = ROOT / "ios/LiveRuntime"
    result = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-DFAMILY_WAKE_TESTING=1",
        "-I"+str(folder), str(folder / "FamilyCallWakeGate.c"), str(harness), "-pthread", "-o", str(binary)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def native_library(tmp_path, *, testing=False):
    target = tmp_path / "window.so"
    source = ROOT / "ios/LiveRuntime/FamilyCallWakeGate.c"
    arguments = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-pthread"]
    if testing:
        arguments.append("-DFAMILY_WAKE_TESTING=1")
    subprocess.run(arguments + [str(source), "-o", str(target)], check=True, capture_output=True, timeout=20)
    return ctypes.CDLL(str(target))


def production_exports(library):
    # Ask the native loader about the executable exports. The Ubuntu 26.04
    # runner's nm repeatedly stalled on the tiny object, before any assertion.
    assert not hasattr(library, "family_call_wake_test_time"), "Test clock exported by production library"
    return library.family_call_wake_arm, library.family_call_wake_consume


def test_clock_override_is_absent_from_running_production_library(tmp_path):
    arm, consume = production_exports(native_library(tmp_path))
    arm.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    consume.argtypes = [ctypes.c_char_p]
    arm.restype = consume.restype = ctypes.c_bool
    voice = b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert arm(b"0123456789abcdef0123456789abcdef", voice, 30)
    assert consume(voice)
    assert not consume(voice)


def test_production_export_check_rejects_a_library_with_the_test_clock(tmp_path):
    with pytest.raises(AssertionError, match="Test clock exported"):
        production_exports(native_library(tmp_path, testing=True))
