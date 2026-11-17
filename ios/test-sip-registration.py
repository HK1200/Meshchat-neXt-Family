#!/usr/bin/env python3
"""Verify the compiled iOS SIP engine against a private digest registrar."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import platform
import re
import secrets
import socket
import subprocess
import threading

ROOT = Path(__file__).resolve().parent


class Registrar:
    def __init__(self):
        self.user = "family-test"
        self.password = secrets.token_hex(16)
        self.realm = "family-private-test"
        self.nonce = secrets.token_hex(16)
        self.authenticated = False
        self.unregistered = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(0.2)
        self.port = self.socket.getsockname()[1]
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        self.socket.close()

    def authorized(self, header):
        fields = {name.lower(): quoted or bare for name, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header)}
        if fields.get("username") != self.user or fields.get("realm") != self.realm or fields.get("nonce") != self.nonce:
            return False
        digest = lambda value: hashlib.md5(value.encode()).hexdigest()
        first = digest(self.user + ":" + self.realm + ":" + self.password)
        second = digest("REGISTER:" + fields.get("uri", ""))
        if fields.get("qop") == "auth":
            value = ":".join((first, self.nonce, fields.get("nc", ""), fields.get("cnonce", ""), "auth", second))
        else:
            value = ":".join((first, self.nonce, second))
        return hmac.compare_digest(digest(value), fields.get("response", ""))

    def serve(self):
        while not self.stopping.is_set():
            try:
                raw, address = self.socket.recvfrom(65535)
            except socket.timeout:
                continue
            lines = raw.decode("utf-8", "replace").split("\r\n")
            if not lines[0].startswith("REGISTER "):
                continue
            headers = []
            values = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers.append((name.lower(), value.strip()))
                    values[name.lower()] = value.strip()
            accepted = self.authorized(values.get("authorization", ""))
            response = ["SIP/2.0 " + ("200 OK" if accepted else "401 Unauthorized")]
            for name, value in headers:
                if name in ("via", "from", "to", "call-id", "cseq"):
                    if name == "to" and ";tag=" not in value:
                        value += ";tag=family-test"
                    response.append(name + ": " + value)
            if accepted:
                self.authenticated = True
                self.unregistered |= values.get("expires") == "0" or "expires=0" in values.get("contact", "")
                if "contact" in values:
                    response.append("Contact: " + values["contact"])
                response.append("Expires: " + ("0" if self.unregistered else "3600"))
            else:
                response.append('WWW-Authenticate: Digest realm="' + self.realm + '", nonce="' + self.nonce + '", algorithm=MD5, qop="auth"')
            response.extend(("Content-Length: 0", "", ""))
            self.socket.sendto("\r\n".join(response).encode(), address)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("simulator")
    args = parser.parse_args()
    arch = platform.machine()
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True).strip()
    directory = ROOT / "RuntimeBuild/sip" / ("iphonesimulator-" + arch)
    executable = directory / "sip-registration-test"
    command = ["xcrun", "--sdk", "iphonesimulator", "clang", "-target", arch + "-apple-ios17.0-simulator", "-isysroot", sdk,
               "-I" + str(ROOT / "LiveRuntime"), "-I" + str(ROOT / "RuntimeBuild/sip/re-4.12.0/include"),
               "-I" + str(ROOT / "RuntimeBuild/sip/baresip-4.12.0/include"),
               str(ROOT / "SIPPolicyTests/registration.c"), str(ROOT / "LiveRuntime/FamilySIP.c"), str(directory / "libFamilySIP.a"),
               "-framework", "AudioToolbox", "-framework", "CoreAudio", "-framework", "CoreFoundation",
               "-framework", "Security", "-framework", "SystemConfiguration", "-lresolv", "-lz", "-o", str(executable)]
    subprocess.run(command, check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(executable)], check=True)
    photo_test = directory / "contact-photo-test"
    subprocess.run(["xcrun", "--sdk", "iphonesimulator", "swiftc", "-target", arch + "-apple-ios17.0-simulator", "-sdk", sdk,
                    str(ROOT / "FamilyLive/FamilyContactPhotoCodec.swift"), str(ROOT / "ContactPhotoTests/main.swift"),
                    "-o", str(photo_test)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(photo_test)], check=True)
    inventory = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "--json"], text=True))
    device = next(device for devices in inventory["devices"].values() for device in devices if device["udid"] == args.simulator)
    booted_here = device["state"] != "Booted"
    if booted_here:
        subprocess.run(["xcrun", "simctl", "boot", args.simulator], check=True)
    subprocess.run(["xcrun", "simctl", "bootstatus", args.simulator, "-b"], check=True, timeout=180)
    registrar = Registrar()
    try:
        # Capture output so the private test password never appears in a command log.
        result = subprocess.run(["xcrun", "simctl", "spawn", args.simulator, str(executable), registrar.user,
                                 str(registrar.port), registrar.password], capture_output=True, text=True, timeout=50)
        if result.returncode or not registrar.authenticated or not registrar.unregistered:
            raise RuntimeError("Native SIP registration/unregistration test failed: " + result.stdout + result.stderr)
        print("Native SIP registration authenticated, then unregistered cleanly")
        photo_result = subprocess.run(["xcrun", "simctl", "spawn", args.simulator, str(photo_test)],
                                      capture_output=True, text=True, timeout=40)
        if photo_result.returncode:
            raise RuntimeError("Native contact-photo checks failed: " + photo_result.stdout + photo_result.stderr)
        print(photo_result.stdout.strip())
    finally:
        registrar.close()
        if booted_here:
            subprocess.run(["xcrun", "simctl", "shutdown", args.simulator], check=False)


if __name__ == "__main__":
    main()
