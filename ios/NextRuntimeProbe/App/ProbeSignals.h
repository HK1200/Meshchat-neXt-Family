#ifndef NEXT_PROBE_SIGNALS_H
#define NEXT_PROBE_SIGNALS_H

#include <stdbool.h>
#include <signal.h>

// Embedded Python disables its default signal installation. A closed TCP
// connection must become EPIPE/OSError, not terminate the whole iOS app.
static inline bool next_prepare_process_signals(void) {
    return signal(SIGPIPE, SIG_IGN) != SIG_ERR;
}

#endif
