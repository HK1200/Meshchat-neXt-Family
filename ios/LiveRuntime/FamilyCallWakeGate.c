// SPDX-License-Identifier: 0BSD
#define _POSIX_C_SOURCE 200809L
#if defined(__APPLE__)
#define _DARWIN_C_SOURCE 1
#endif
#include "FamilyCallWakeGate.h"
#include <pthread.h>
#include <string.h>
#include <time.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static char pending_call[33], pending_voice[33];
static uint64_t opened_at, expires_at;
#ifdef FAMILY_WAKE_TESTING
static uint64_t test_time;
static bool test_clock_available = true;
void family_call_wake_test_time(uint64_t milliseconds, bool available) {
    pthread_mutex_lock(&mutex);
    test_time = milliseconds; test_clock_available = available;
    pthread_mutex_unlock(&mutex);
}
#endif
static bool now_ms(uint64_t *value) {
#ifdef FAMILY_WAKE_TESTING
    *value = test_time; return test_clock_available;
#else
    struct timespec now;
    // Keep expiry advancing across device sleep. Apple documents its raw
    // clock as the continuous clock: developer.apple.com/documentation/kernel/1646199-mach_continuous_time
#if defined(__APPLE__)
    const clockid_t clock = CLOCK_MONOTONIC_RAW;
#elif defined(CLOCK_BOOTTIME)
    const clockid_t clock = CLOCK_BOOTTIME;
#else
    const clockid_t clock = CLOCK_MONOTONIC;
#endif
    if (clock_gettime(clock, &now) != 0 || now.tv_sec < 0 ||
        (uint64_t)now.tv_sec > UINT64_MAX / 1000 || now.tv_nsec < 0 || now.tv_nsec >= 1000000000) return false;
    uint64_t seconds = (uint64_t)now.tv_sec * 1000;
    uint64_t fraction = (uint64_t)now.tv_nsec / 1000000;
    if (seconds > UINT64_MAX - fraction) return false;
    *value = seconds + fraction; return true;
#endif
}
static bool hex32(const char *text) {
    if (!text) return false;
    for (unsigned i = 0; i < 32; ++i) {
        if (!((text[i] >= '0' && text[i] <= '9') || (text[i] >= 'a' && text[i] <= 'f'))) return false;
    }
    return text[32] == 0;
}
static void clear_locked(void) {
    memset(pending_call, 0, sizeof pending_call);
    memset(pending_voice, 0, sizeof pending_voice);
    opened_at = expires_at = 0;
}
static bool live_locked(uint64_t now) {
    if (!pending_call[0] || now < opened_at || now >= expires_at) {
        clear_locked(); return false;
    }
    return true;
}
bool family_call_wake_arm(const char *call_id, const char *voice, uint32_t seconds) {
    if (!hex32(call_id) || !hex32(voice) || seconds < 1 || seconds > 30) return false;
    pthread_mutex_lock(&mutex);
    uint64_t now;
    bool accepted = false;
    if (!now_ms(&now)) clear_locked();
    else if (!live_locked(now) && now <= UINT64_MAX - (uint64_t)seconds * 1000) {
        memcpy(pending_call, call_id, 33); memcpy(pending_voice, voice, 33);
        opened_at = now; expires_at = now + (uint64_t)seconds * 1000; accepted = true;
    }
    pthread_mutex_unlock(&mutex);
    return accepted;
}
bool family_call_wake_consume(const char *voice) {
    if (!hex32(voice)) return false;
    pthread_mutex_lock(&mutex);
    uint64_t now;
    bool accepted = false;
    if (!now_ms(&now)) clear_locked();
    else if (live_locked(now) && strcmp(pending_voice, voice) == 0) {
        accepted = true; clear_locked();
    }
    pthread_mutex_unlock(&mutex);
    return accepted;
}
void family_call_wake_cancel(const char *call_id) {
    if (!hex32(call_id)) return;
    pthread_mutex_lock(&mutex);
    if (strcmp(pending_call, call_id) == 0) clear_locked();
    pthread_mutex_unlock(&mutex);
}
void family_call_wake_reset(void) {
    pthread_mutex_lock(&mutex); clear_locked(); pthread_mutex_unlock(&mutex);
}
