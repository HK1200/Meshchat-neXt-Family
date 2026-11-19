import Foundation

let extensionAddress = FamilySIPAddress("400471")!
assert(extensionAddress.uri == "sip:400471@premium.hamsoverip.com:5160")
assert(FamilySIPAddress("Mom <SIP:400471@PREMIUM.HAMSOVERIP.COM:5160>;tag=123") == extensionAddress)
assert(FamilySIPAddress("400471@example.org")?.port == 5060)
for invalid in ["", "sip:user@", "sip:user@example.org:0", "sip:user@example.org:65536", "sip:user@evil.org\r\nContact: x", "sip:one@two@three", "sip:user@example.org:bad"] {
    assert(FamilySIPAddress(invalid) == nil, "Accepted invalid SIP address")
}
let resolved = Set(["192.0.2.20"])
let incoming = FamilySIPAddress("sip:400471@192.0.2.20:5160")!
assert(extensionAddress.matches(incoming, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: resolved))
assert(!extensionAddress.matches(incoming, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: []))
assert(!extensionAddress.matches(FamilySIPAddress("sip:other@192.0.2.20:5160")!, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: resolved))
assert(extensionAddress.matches(FamilySIPAddress("sip:400471@192.0.2.20:5060")!, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: resolved))
assert(!extensionAddress.matches(FamilySIPAddress("sip:400471@192.0.2.20:9999")!, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: resolved))
print("SIP address and provider-IP approval checks passed")
