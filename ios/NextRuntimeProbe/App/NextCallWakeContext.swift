// SPDX-License-Identifier: 0BSD
import Foundation

/// Native enrollment snapshot only. No private key enters JavaScript, an HTTP
/// endpoint, a provider request or diagnostic output through this type.
struct NextCallWakeContext: Equatable {
    let recipientPrivateKey: Data
    let recipientPublicKey: Data
    let audience: String
    let approvedNames: [String: String]
}

