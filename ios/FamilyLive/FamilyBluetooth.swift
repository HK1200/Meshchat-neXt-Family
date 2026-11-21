import CoreBluetooth
import Foundation

/// Owns each selected radio independently on a serial queue.
final class FamilyBluetooth: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    static let shared = FamilyBluetooth()
    private let queue = DispatchQueue(label: "org.meshchat.family.bluetooth")
    private var central: CBCentralManager!
    private let service = CBUUID(string: "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
    private let receive = CBUUID(string: "6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
    private let transmit = CBUUID(string: "6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
    private var devices: [UUID: CBPeripheral] = [:]
    private var sessions: [UUID: Session] = [:]

    private final class Session {
        let peripheral: CBPeripheral
        let stream: Bool
        var writer: CBCharacteristic?
        var events: [[String: Any]] = []
        var chunks: [Data] = []
        var writing = false
        var ready = false
        init(_ peripheral: CBPeripheral, stream: Bool) {
            self.peripheral = peripheral
            self.stream = stream
        }
    }

    override private init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: queue)
    }

    // Python calls this off the Bluetooth queue with its interpreter lock released.
    func request(_ text: String) -> String {
        guard let data = text.data(using: .utf8),
              let request = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "{\"error\":\"Invalid Bluetooth request\"}"
        }
        let reply: [String: Any] = queue.sync { perform(request) }
        guard let encoded = try? JSONSerialization.data(withJSONObject: reply),
              let result = String(data: encoded, encoding: .utf8) else { return "{}" }
        return result
    }

    private func perform(_ request: [String: Any]) -> [String: Any] {
        let operation = request["operation"] as? String ?? ""
        if operation == "devices" {
            return ["state": central.state.rawValue, "devices": devices.values.map {
                ["id": $0.identifier.uuidString, "name": $0.name ?? "Bluetooth radio"]
            }]
        }
        if operation == "scan" {
            guard central.state == .poweredOn else { return ["error": "Enable Bluetooth and allow radio access in the system prompt"] }
            central.scanForPeripherals(withServices: [service])
            queue.asyncAfter(deadline: .now() + 8) { self.central.stopScan() }
            return ["ok": true]
        }
        guard let address = request["id"] as? String, let id = UUID(uuidString: address) else {
            return ["error": "Select a Bluetooth radio"]
        }
        if operation == "open" {
            guard central.state == .poweredOn else { return ["error": "Bluetooth is unavailable"] }
            guard sessions[id] == nil else { return ["error": "Radio is already in use"] }
            guard let peripheral = devices[id] ?? central.retrievePeripherals(withIdentifiers: [id]).first else {
                return ["error": "Radio was not found. Scan again nearby."]
            }
            guard peripheral.state == .disconnected else { return ["error": "Radio is disconnecting. Try again shortly."] }
            let session = Session(peripheral, stream: request["stream"] as? Bool ?? false)
            sessions[id] = session
            peripheral.delegate = self
            central.connect(peripheral)
            queue.asyncAfter(deadline: .now() + 180) {
                if self.sessions[id] === session && !session.ready {
                    self.fail(session, "Bluetooth connection timed out")
                }
            }
            return ["ok": true]
        }
        if operation == "close" {
            if let session = sessions.removeValue(forKey: id) {
                central.cancelPeripheralConnection(session.peripheral)
            }
            return ["ok": true]
        }
        guard let session = sessions[id] else { return ["error": "Radio session is closed"] }
        if operation == "poll" {
            let events = session.events
            session.events.removeAll(keepingCapacity: true)
            return ["events": events]
        }
        if operation == "send" {
            guard session.ready, session.chunks.isEmpty, !session.writing,
                  let writer = session.writer,
                  let encoded = request["data"] as? String,
                  let payload = Data(base64Encoded: encoded), !payload.isEmpty, payload.count <= 4096 else {
                return ["error": "Radio is unavailable or a write is already pending"]
            }
            let type: CBCharacteristicWriteType = writer.properties.contains(.write) ? .withResponse : .withoutResponse
            // MeshCore commands are single GATT frames. RNode KISS is a byte stream.
            // Stay within the negotiated ATT payload instead of relying on long writes.
            let size = min(session.peripheral.maximumWriteValueLength(for: type),
                           session.peripheral.maximumWriteValueLength(for: .withoutResponse))
            if !session.stream && payload.count > size {
                return ["error": "MeshCore command exceeds this radio’s negotiated Bluetooth frame size"]
            }
            guard size > 0 else { return ["error": "Radio has no writable Bluetooth payload"] }
            for offset in stride(from: 0, to: payload.count, by: size) {
                session.chunks.append(payload.subdata(in: offset..<min(offset + size, payload.count)))
            }
            writeNext(session)
            return ["ok": true]
        }
        return ["error": "Unknown Bluetooth operation"]
    }

    private func emit(_ session: Session, _ event: [String: Any]) {
        // Stop an unread session instead of silently dropping protocol bytes.
        guard session.events.count < 1024 else {
            session.events = [["type": "error", "detail": "Bluetooth receive queue overflow"], ["type": "closed"]]
            session.ready = false
            central.cancelPeripheralConnection(session.peripheral)
            return
        }
        session.events.append(event)
    }

    private func fail(_ session: Session, _ message: String) {
        session.ready = false
        session.chunks.removeAll()
        session.writing = false
        emit(session, ["type": "error", "detail": message])
        central.cancelPeripheralConnection(session.peripheral)
    }

    private func writeNext(_ session: Session) {
        guard session.ready, !session.writing, let writer = session.writer else { return }
        let acknowledged = writer.properties.contains(.write)
        while !session.chunks.isEmpty {
            if !acknowledged && !session.peripheral.canSendWriteWithoutResponse { return }
            let chunk = session.chunks.removeFirst()
            session.writing = acknowledged
            session.peripheral.writeValue(chunk, for: writer, type: acknowledged ? .withResponse : .withoutResponse)
            if acknowledged { return }
        }
        emit(session, ["type": "written"])
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state != .poweredOn {
            for session in sessions.values { fail(session, "Bluetooth is unavailable") }
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        devices[peripheral.identifier] = peripheral
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        peripheral.discoverServices([service])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        emit(session, ["type": "error", "detail": error?.localizedDescription ?? "Bluetooth connection failed"])
        emit(session, ["type": "closed"])
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        session.ready = false
        session.chunks.removeAll()
        session.writing = false
        emit(session, ["type": "closed"])
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        guard error == nil, let uart = peripheral.services?.first(where: { $0.uuid == service }) else {
            fail(session, error?.localizedDescription ?? "Radio UART service is missing")
            return
        }
        peripheral.discoverCharacteristics([receive, transmit], for: uart)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        guard error == nil,
              let writer = service.characteristics?.first(where: { $0.uuid == transmit }),
              writer.properties.contains(.write) || writer.properties.contains(.writeWithoutResponse),
              let reader = service.characteristics?.first(where: { $0.uuid == receive }),
              reader.properties.contains(.notify) || reader.properties.contains(.indicate) else {
            fail(session, error?.localizedDescription ?? "Radio UART characteristics are missing")
            return
        }
        session.writer = writer
        peripheral.setNotifyValue(true, for: reader)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        guard error == nil, characteristic.isNotifying else {
            fail(session, error?.localizedDescription ?? "Radio notifications were refused")
            return
        }
        session.ready = true
        emit(session, ["type": "ready"])
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        if let error { fail(session, error.localizedDescription); return }
        if let data = characteristic.value, !data.isEmpty {
            emit(session, ["type": "data", "data": data.base64EncodedString()])
            NotificationCenter.default.post(name: .familyRadioData, object: nil)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let session = sessions[peripheral.identifier] else { return }
        if let error { fail(session, error.localizedDescription); return }
        session.writing = false
        writeNext(session)
    }

    func peripheralIsReady(toSendWriteWithoutResponse peripheral: CBPeripheral) {
        if let session = sessions[peripheral.identifier], !session.chunks.isEmpty { writeNext(session) }
    }
}
