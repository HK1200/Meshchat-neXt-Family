import Foundation

/// Keep ready speaker frames ahead of microphone encoding on the serial PCM
/// worker. Encoding may take longer with Codec2; it must not delay scheduling
/// audio which is already decoded. Capture is still sent exactly once.
struct FamilyVoicePCMExchange {
    static let frameBytes = 1_920
    static let captureLimit = 11_520

    static func run(input: Data, availableFrames: Int,
                    exchange: (Data, Int) -> Data, schedule: (Data) -> Bool) {
        let capacity = max(0, min(3, availableFrames)) * frameBytes
        if capacity > 0 {
            let output = exchange(Data(), capacity)
            if !output.isEmpty, output.count <= capacity, output.count % frameBytes == 0 {
                for offset in stride(from: 0, to: output.count, by: frameBytes) {
                    if !schedule(output.subdata(in: offset..<(offset + frameBytes))) { break }
                }
            }
        }
        // A full player or absent/malformed incoming audio cannot suppress the
        // microphone. Completion-only refills have no capture payload.
        if !input.isEmpty, input.count <= captureLimit, input.count % 2 == 0 {
            _ = exchange(input, 0)
        }
    }
}
