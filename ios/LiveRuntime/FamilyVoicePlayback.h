/* SPDX-License-Identifier: 0BSD */
#ifndef FAMILY_VOICE_PLAYBACK_H
#define FAMILY_VOICE_PLAYBACK_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* The embedding translation unit includes CPython first. Drain the available
 * 20 ms slots after a delayed timer, retaining the existing 60 ms native limit.
 * A capture push belongs to the caller and must happen only once per exchange. */
static inline size_t family_voice_pull_frames(PyObject *identifier, PyObject *pull,
                                              uint8_t *output, size_t capacity) {
    const size_t frame_bytes = 1920;
    size_t frames = capacity / frame_bytes;
    if (!identifier || !pull || !output || !frames) return 0;
    if (frames > 3) frames = 3;
    size_t count = 0;
    for (size_t frame = 0; frame < frames; frame++) {
        PyObject *received = PyObject_CallOneArg(pull, identifier);
        char *pcm = NULL;
        Py_ssize_t size = 0;
        int valid = received && PyBytes_Check(received) &&
            PyBytes_AsStringAndSize(received, &pcm, &size) == 0 &&
            size == (Py_ssize_t)frame_bytes;
        if (valid) {
            memcpy(output + count, pcm, frame_bytes);
            count += frame_bytes;
        }
        Py_XDECREF(received);
        if (!valid) break;
    }
    return count;
}
#endif
