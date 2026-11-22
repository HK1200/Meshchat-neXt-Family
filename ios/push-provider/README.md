# Optional Family and neXt mailbox alerts

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
    "app": "family",
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

The neXt iOS development preview has **Offline mailbox → Recipient mailbox alerts** for saving and removing sender routes. Desktop/Android neXt uses **Settings → neXt Family → Recipient mailbox alerts**. These controls accept only the provider, audience and relay; never a recipient's enrollment secret or APNs token. Saving settings makes no provider request.

On iPad or iPhone, a guardian can edit an approved Reticulum contact and open **Private mailbox push route** to save or remove its route. Family and neXt also read a sender-local `mailbox-push-routes.json`. In Family, place it in the app's backend state directory (on iPad, `Library/Application Support/FamilyTCP` inside Family's container). In neXt, place it in the sending identity's storage directory beside `database.db`. Use the file for operator-managed setups.

```json
{
  "<recipient LXMF address>": {
    "provider": "https://alerts.example.org",
    "audience": "unique-name-for-this-private-provider",
    "relay": "<recipient's LXMF propagation node address>"
  }
}
```

Both Reticulum addresses use lowercase hex. Provision the approved recipient's verified Reticulum identity before sending to an offline contact. Family sends routed messages through the listed relay. If Family has a mailbox of its own configured, the route must use that same relay. In neXt, select the listed propagation node and use **Propagated** delivery, or allow the standard failure fallback to that node. Other transmission methods keep their existing behavior.

After LXMF confirms transfer to that relay, the client submits a signed hint. It contains the recipient address, the encrypted packet hash, sender public key, timestamp, and signature. Message content and attachments stay in LXMF. Clients retry transient errors briefly, then leave the relay delivery status as-is.

HTTP 204 means the provider accepted the alert or already recorded it. A caller can retry a temporary 429 or 503 within the five-minute hint window. A 404 means the encrypted message is not currently stored. Recipients can use a compatible iPad client to open Family and fetch the mailbox after the generic alert. APNs delivery depends on the network, the iPad notification settings, and Apple. The provider needs valid Apple credentials and a token from a signed, push-enabled build for a live test.

## Receiving alerts in neXt iOS

Development source after neXt 0.1.21 adds **Offline mailbox → Mailbox push alerts**. This is separate from **Recipient mailbox alerts**, which configures sending hints. Save a mailbox first, enter a private provider's HTTPS address and enrollment code, and explicitly select verified saved contacts. New phonebook contacts do not automatically get push permission. The enrollment code remains in neXt's own Keychain; Family's settings and credentials are not accessed.

Run a separate provider instance for neXt with `apns.app` set to `next` and the exact signed neXt bundle identifier as `apns.topic`. Family remains the default app. Each instance uses its fixed configured Apple topic and generic app-specific alert; senders cannot choose the topic or alert text. The APNs environment must match the signing profile. For a push-enabled neXt device archive, set `NEXT_APNS_ENVIRONMENT` to `development` or `production`; the build adds its APNs entitlement only when explicitly requested. A matching paid-developer provisioning profile is still required before signing. Personal previews leave this setting empty and cannot enable Apple push enrollment.

A visible push alert can arrive while iOS suspends neXt. Tapping it opens Messages and retrieves the encrypted mailbox while the app is running. This does not promise silent retrieval while fully suspended, instant radio delivery, or background call ringing. Token rotation and contact revocations sync when neXt runs. Turning alerts off remains pending until the provider acknowledges token removal. No live Apple push delivery has been qualified yet; Apple enrollment is still on hold.

## Notification metadata retention

The reference provider retains recipient/message identifiers and acceptance times
for duplicate suppression and rate limiting for one hour. Its HTTP service
prunes older records during idle operation, at most once per minute. This is
longer than the five-minute signed-hint window, so removing expired records does
not make an original expired hint valid again. Normal clients retry the same
hint only within that window. A newly signed hint is a new authorized request.

Acknowledged turn-off removes the active registration, including its Apple token
and approved-sender keys, rather than retaining an empty registration row. Old
empty rows are removed by cleanup too. SQLite secure deletion clears reusable
pages in the active database. Operator configuration, access logs, filesystem
snapshots and backups have separate retention; do not promise that app turn-off
erases those copies or the relay's encrypted mailbox. Keep those stores private
and define their retention before deploying the service.
