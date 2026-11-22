import CoreFoundation
import CryptoKit
import Foundation

/// Validates a private call intent before it can enter native call handling.
/// This parser does not register PushKit, report CallKit calls or start media.
struct FamilyCallWake: Equatable {
    let recipient: String
    let call: UUID
    let sender: String
    let callerVoice: String
    let issued: Int

    enum Invalid: Error { case payload, identity, signature, expired, approval }
    private static let info = Data("neXt Reticulum call payload v1\0".utf8)

    static func voiceAddress(publicKey: Data) throws -> String {
        guard publicKey.count == 64 else { throw Invalid.identity }
        let name = Data(SHA256.hash(data: Data("lxst.telephony".utf8)).prefix(10))
        let identity = Data(SHA256.hash(data: publicKey).prefix(16))
        return hex(Data(SHA256.hash(data: name + identity).prefix(16)))
    }

    static func decode(_ data: Data, recipientPrivateKey: Data, recipientPublicKey: Data,
                       audience: String, approvedCallers: Set<String>, now: Int) throws -> Self {
        guard data.count <= 5120,
              recipientPrivateKey.count == 32, recipientPublicKey.count == 64,
              audience.range(of: "^[A-Za-z0-9 _.-]{1,128}$", options: .regularExpression) != nil,
              approvedCallers.count <= 256,
              let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(envelope.keys) == ["aps", "next_call"],
              let aps = envelope["aps"] as? [String: Any], aps.isEmpty,
              let sealed = envelope["next_call"] as? [String: Any],
              Set(sealed.keys) == ["v", "key", "nonce", "cipher"],
              integer(sealed["v"]) == 1,
              let ephemeral = base64(sealed["key"], count: 32),
              let nonce = base64(sealed["nonce"], count: 12),
              let cipher = base64(sealed["cipher"]), cipher.count >= 16, cipher.count <= 2064 else {
            throw Invalid.payload
        }
        let own = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: recipientPrivateKey)
        guard own.publicKey.rawRepresentation == recipientPublicKey.prefix(32) else { throw Invalid.identity }
        let recipient = try voiceAddress(publicKey: recipientPublicKey)
        let remote = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: ephemeral)
        let shared = try own.sharedSecretFromKeyAgreement(with: remote)
        let key = shared.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(), sharedInfo: info, outputByteCount: 32)
        let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: nonce),
            ciphertext: cipher.dropLast(16), tag: cipher.suffix(16))
        let plaintext = try AES.GCM.open(box, using: key, authenticating: info + (unhex(recipient, count: 16) ?? Data()))
        guard plaintext.count <= 2048,
              let hint = try JSONSerialization.jsonObject(with: plaintext) as? [String: Any],
              Set(hint.keys) == ["recipient", "call", "sender", "issued", "signature"],
              hint["recipient"] as? String == recipient,
              let callText = hint["call"] as? String, let callBytes = unhex(callText, count: 16),
              let sender = hint["sender"] as? String, let senderKey = unhex(sender, count: 64),
              let signatureText = hint["signature"] as? String, let signature = unhex(signatureText, count: 64),
              let issued = integer(hint["issued"]), issued >= 0, issued <= 9_007_199_254_740_991 else {
            throw Invalid.payload
        }
        guard now >= 0, issued >= max(0, now - 30), issued <= now.addingReportingOverflow(10).partialValue else {
            throw Invalid.expired
        }
        let caller = try voiceAddress(publicKey: senderKey)
        guard approvedCallers.contains(caller) else { throw Invalid.approval }
        let signed: [String: Any] = ["audience": audience, "recipient": recipient,
            "call": callText, "sender": sender, "issued": issued]
        let canonical = try JSONSerialization.data(withJSONObject: signed, options: [.sortedKeys, .withoutEscapingSlashes])
        let verifier = try Curve25519.Signing.PublicKey(rawRepresentation: senderKey.suffix(32))
        guard verifier.isValidSignature(signature, for: Data("neXt Reticulum call wake v1\0".utf8) + canonical) else {
            throw Invalid.signature
        }
        let b = Array(callBytes)
        let uuid = UUID(uuid: (b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
                               b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]))
        return Self(recipient: recipient, call: uuid, sender: sender, callerVoice: caller, issued: issued)
    }

    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded(.towardZero) == number.doubleValue,
              number.doubleValue >= 0, number.doubleValue <= 9_007_199_254_740_991 else { return nil }
        return number.intValue
    }
    private static func base64(_ value: Any?, count: Int? = nil) -> Data? {
        guard let text = value as? String, let bytes = Data(base64Encoded: text),
              bytes.base64EncodedString() == text, count == nil || bytes.count == count else { return nil }
        return bytes
    }
    private static func unhex(_ value: String, count: Int) -> Data? {
        guard value.count == count * 2,
              value.range(of: "^[a-f0-9]+$", options: .regularExpression) != nil else { return nil }
        var bytes = Data()
        var offset = value.startIndex
        for _ in 0..<count {
            let end = value.index(offset, offsetBy: 2)
            guard let byte = UInt8(value[offset..<end], radix: 16) else { return nil }
            bytes.append(byte); offset = end
        }
        return bytes
    }
    private static func hex(_ value: Data) -> String { value.map { String(format: "%02x", $0) }.joined() }
}
