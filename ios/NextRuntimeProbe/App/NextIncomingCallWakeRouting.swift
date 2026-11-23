// SPDX-License-Identifier: 0BSD
import Foundation

/// Only a native authenticated wake owner may offer a pending call for adoption.
@MainActor
protocol NextIncomingCallWakeRouting: AnyObject {
    func pendingIncoming(peer: String, service: FamilySystemCallKey.Service) -> FamilySystemCallKey?
    func attached(_ pending: FamilySystemCallKey, to key: FamilySystemCallKey)
}

