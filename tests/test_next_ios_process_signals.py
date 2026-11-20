"""Prove a closed peer becomes an error instead of killing the embedded app."""
import os
from pathlib import Path
import shutil
import signal
import subprocess

import pytest


@pytest.mark.skipif(os.name != "posix" or shutil.which("cc") is None,
                    reason="Requires a POSIX host C compiler")
def test_embedded_python_bridge_survives_closed_socket_write(tmp_path):
    include = Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe/App"
    source = tmp_path / "closed-peer.c"
    source.write_text(r'''
#include "ProbeSignals.h"
#include <errno.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    (void)argv;
    if (signal(SIGPIPE, SIG_DFL) == SIG_ERR) return 2;
    if (argc > 1 && !next_prepare_process_signals()) return 3;
    int sockets[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) != 0) return 4;
    close(sockets[1]);
    int sent = send(sockets[0], "test", 4, 0);
    int error = errno;
    close(sockets[0]);
    return sent == -1 && error == EPIPE ? 0 : 5;
}
''')
    binary = tmp_path / "closed-peer"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(include),
                    str(source), "-o", str(binary)], check=True, capture_output=True)
    baseline = subprocess.run([str(binary)], capture_output=True)
    assert baseline.returncode == -signal.SIGPIPE
    protected = subprocess.run([str(binary), "protected"], capture_output=True)
    assert protected.returncode == 0
