# Optional Family mailbox alerts

Run this provider alongside a private LXMF propagation node. It reads the mailbox spool and sends a generic Apple alert after an approved sender signs a hint for a stored message. It does not decrypt mail. The APNs payload contains only the generic alert, and APNs request identifiers are derived with a private key rather than exposing the LXMF message hash.

## Run locally

Use Python with `cryptography`, curl with HTTP/2 support, and a private directory for the SQLite state. Give the provider read-only access to the relay's LXMF `messagestore`. Start it with `python provider.py /path/to/private-config.json`. It listens on loopback. For delivery over the network, put an HTTPS reverse proxy in front of `POST /v1/mailbox-alert` and `POST /v1/subscription`, with request limits of 2 KiB and 36,000 bytes respectively, request timeouts, and ingress rate limiting. Keep the configuration, SQLite database, and APNs key private.

```json
{
  "audience": "unique-name-for-this-private-provider",
  "port": 8087,
  "spool": "/path/to/private-relay/lxmf/messagestore",
  "database": "/path/to/private-state/alerts.sqlite",
  "subscriptions": {
    "<recipient LXMF address in lowercase hex>": {
      "enrollment_hash": "<SHA-256 of the 32 raw enrollment-code bytes in hex>"
    }
  },
  "apns": {
    "environment": "development",
    "topic": "<push-enabled Family bundle identifier>",
    "team": "<Apple developer team ID>",
    "key_id": "<Apple APNs key ID>",
    "key_file": "/path/to/private/AuthKey.p8",
    "id_key": "<32 random bytes in lowercase hex>"
  }
}
```

The operator generates a random 32-byte enrollment code, stores its SHA-256 hash in the recipient's configuration, and gives the guardian the HTTPS provider address and hex code. For example, generate a code locally with `openssl rand -hex 32`. Do not send the code to Apple. The guardian opens **Guardian settings → Mailbox push alerts** after saving their mailbox and chooses **Enable push alerts**. Family stores the code in Keychain and authenticates its token and approved Reticulum key updates with `Authorization: Bearer <code>`. A recipient can have one active token per provider. Removed contacts and token changes are synced when Family is open.

**Turn off push alerts** requests deletion at the provider and confirms once the provider acknowledges it. If either side is offline, the app shows that turn-off is pending and retries when reopened. An operator can also remove or rotate the enrollment record and restart the provider to block further requests. The legacy static subscription format with explicit `token` and `senders` still works for operator-managed deployments.

A push-enabled signed build needs an Apple profile that permits APNs. Set `FAMILY_APNS_ENVIRONMENT=development` for the development profile or `production` for a distribution profile when archiving. The archive script applies the entitlement only when that setting is present. Use the matching APNs environment and exact signed bundle identifier in the provider. Existing personal sideload builds can show the guardian screen and exercise registration failure handling. They still use local notifications and mailbox recovery.

## Send a hint

After LXMF confirms the private relay accepted a propagated message, a compatible sender can POST JSON containing the lowercase-hex `recipient`, LXMF `message.transient_id` as `message`, the complete Reticulum public key as `sender`, integer Unix seconds as `issued`, and the hex Reticulum signature as `signature`. Sign the output of `signed_bytes(hint, audience)` with that sender's identity. The helper defines the protocol's canonical JSON and domain separator. Existing LXMF clients can still send and receive normally. They will not raise a remote alert unless they also send the hint.

HTTP 204 means the provider accepted the alert or already recorded it. A caller can retry a temporary 429 or 503 within the five-minute hint window. A 404 means the encrypted message is not currently stored. Recipients can use a compatible iPad client to open Family and fetch the mailbox after the generic alert. APNs delivery depends on the network, the iPad notification settings, and Apple. The provider needs valid Apple credentials and a token from a signed, push-enabled build for a live test.
