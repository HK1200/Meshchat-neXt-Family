# Report a security vulnerability

Use [GitHub’s private vulnerability report form](https://github.com/HK1200/Meshchat-neXt-Family/security/advisories/new) for security issues in neXt Family. Include the affected version, platform, steps to reproduce and the impact.

Before sharing diagnostics, remove passwords, private keys, contact addresses, message contents and precise locations. Use the [public issue tracker](https://github.com/HK1200/Meshchat-neXt-Family/issues) for ordinary bugs.

## Build-input and test-fixture findings

- The neXt iOS HTTP runtime is installed from
  `ios/NextRuntimeProbe/requirements.lock` with `--require-hashes`. Its versions
  follow the reviewed test lock; no native platform wheel is substituted into
  the embedded pure-Python runtime.
- The private HTTPS test provider explicitly requires TLS 1.2 or later.
- `ios/test-sip-registration.py` and `tests/test_ios_sip_signaling_fixture.py`
  reproduce SIP's legacy MD5 Digest authentication using randomly generated,
  temporary test credentials. They do not hash or store personal account
  passwords. Keep this interoperability coverage; changing the digest just to
  silence a password-storage finding would stop testing the negotiated protocol.
  Review those specific findings as test-fixture usage, not as a production
  password-storage implementation.
- Necessary Android binary inputs and their source/reproduction details are
  documented in [BUILDING.md](docs/BUILDING.md#bundled-android-binaries) and checked
  against `gradle/android-binaries.sha256`. Do not remove required libraries or
  disable integrity checks to improve a binary-artifact score.
- CodeQL runs on main pushes and pull requests through `security.yml`. Check the
  actual commit's completed analyses when assessing a historical Scorecard SAST
  warning. [Scorecard's implementation](https://github.com/ossf/scorecard/blob/main/checks/raw/sast.go)
  also considers merged-request history; that signal is separate from an
  individual successful scan.
