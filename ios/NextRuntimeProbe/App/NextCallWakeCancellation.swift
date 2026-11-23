// SPDX-License-Identifier: 0BSD
import CryptoKit
import Foundation

/// A provider's state label alone cannot end a call. Only the original caller's
/// domain-separated cancellation signature for this exact pending intent can.
struct NextCallWakeCancellation {
    private struct Reply: Decodable { let state: String; let hint: Hint }
    private struct Hint: Decodable {
        let recipient: String; let call: String; let sender: String
        let issued: Int; let signature: String
    }
    static func verified(_ data: Data, wake: FamilyCallWake, audience: String, now: Int) -> Bool {
        do {
            guard data.count <= 2304, now >= 0, now <= 9_007_199_254_740_981,
                  audience.range(of: #"\A[A-Za-z0-9 _.-]{1,128}\z"#, options: .regularExpression) != nil,
                  let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  Set(object.keys) == ["state", "hint"],
                  let hintObject = object["hint"] as? [String: Any],
                  Set(hintObject.keys) == ["recipient", "call", "sender", "issued", "signature"] else { return false }
            let reply = try JSONDecoder().decode(Reply.self, from: data), hint = reply.hint
            let call = wake.call.uuidString.lowercased().replacingOccurrences(of: "-", with: "")
            guard reply.state == "cancelled", hint.recipient == wake.recipient, hint.call == call,
                  hint.sender == wake.sender, hint.issued >= wake.issued,
                  hint.issued >= max(0, now - 30), hint.issued <= now + 10 else { return false }
            let sender = try NextCallWakePolicy.publicKey(hint.sender)
            let signature = try NextCallWakePolicy.publicKey(hint.signature)
            guard try FamilyCallWake.voiceAddress(publicKey: sender) == wake.callerVoice else { return false }
            let canonical: [String: Any] = ["audience": audience, "recipient": hint.recipient,
                "call": hint.call, "sender": hint.sender, "issued": hint.issued]
            let bytes = try JSONSerialization.data(withJSONObject: canonical, options: [.sortedKeys, .withoutEscapingSlashes])
            let verifier = try Curve25519.Signing.PublicKey(rawRepresentation: sender.suffix(32))
            return verifier.isValidSignature(signature, for: Data("neXt Reticulum call cancel v1\0".utf8) + bytes)
        } catch { return false }
    }
}
