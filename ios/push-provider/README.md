# Optional Family mailbox alerts

Run this provider alongside a private LXMF propagation node. It reads the mailbox spool and sends a generic Apple alert after an approved sender signs a hint for a stored message. It does not decrypt mail. The APNs payload contains only the generic alert, and APNs request identifiers are derived with a private key rather than exposing the LXMF message hash.

## Run locally

Use Python with `cryptography`, curl with HTTP/2 support, and a private directory for the SQLite state. Give the provider read-only access to the relay's LXMF `messagestore`. Start it with `python provider.py /path/to/private-config.json`. It listens on loopback. For delivery over the network, put an HTTPS reverse proxy in front of `POST /v1/mailbox-alert`, with a 2 KiB request limit, request timeouts, and ingress rate limiting. Keep the configuration, SQLite database, and APNs key private.

```json
{
  "audience": "unique-name-for-this-private-provider",
  "port": 8087,
  "spool": "/path/to/private-relay/lxmf/messagestore",
  "database": "/path/to/private-state/alerts.sqlite",
  "subscriptions": {
    "<recipient LXMF address in lowercase hex>": {
      "token": "<APNs device token in lowercase hex>",
      "senders": ["<guardian-approved 64-byte Reticulum public key in lowercase hex>"]
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

An operator adds a subscription only after guardian opt-in and selects the approved sender keys. Restart after changing a token or approval list. To turn alerts off, remove the recipient and restart. Family's mailbox and Reticulum delivery work independently of this provider. The current Family test app does not register APNs tokens or provision subscriptions.

## Send a hint

After LXMF confirms the private relay accepted a propagated message, a compatible sender can POST JSON containing the lowercase-hex `recipient`, LXMF `message.transient_id` as `message`, the complete Reticulum public key as `sender`, integer Unix seconds as `issued`, and the hex Reticulum signature as `signature`. Sign the output of `signed_bytes(hint, audience)` with that sender's identity. The helper defines the protocol's canonical JSON and domain separator. Existing LXMF clients can still send and receive normally. They will not raise a remote alert unless they also send the hint.

HTTP 204 means the provider accepted the alert or already recorded it. A caller can retry a temporary 429 or 503 within the five-minute hint window. A 404 means the encrypted message is not currently stored. Recipients can use a compatible iPad client to open Family and fetch the mailbox after the generic alert. APNs delivery depends on the network, the iPad notification settings, and Apple. The provider needs valid Apple credentials and a token from a signed, push-enabled build for a live test.
