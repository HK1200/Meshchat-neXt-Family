import AVFoundation
import UIKit

@MainActor
enum FamilyCallAudioSession {
    static func configure() throws {
        var options: AVAudioSession.CategoryOptions = [.allowBluetooth]
        if UIDevice.current.userInterfaceIdiom == .pad { options.insert(.defaultToSpeaker) }
        try AVAudioSession.sharedInstance().setCategory(.playAndRecord, mode: .voiceChat, options: options)
    }
    static var hasExternalOutput: Bool {
        AVAudioSession.sharedInstance().currentRoute.outputs.contains {
            $0.portType != .builtInReceiver && $0.portType != .builtInSpeaker
        }
    }
}
