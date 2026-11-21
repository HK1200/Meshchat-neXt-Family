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

let ipv6 = FamilySIPAddress("sip:400471@[2001:db8::20]:5160")!
assert(ipv6.host == "2001:db8::20" && ipv6.uri == "sip:400471@[2001:db8::20]:5160")
assert(FamilySIPAddress("sip:400471@[2001:0DB8:0:0:0:0:0:20]:5160") == ipv6)
assert(FamilySIPAddress("400471", defaultHost: "2001:db8::20", defaultPort: 5160) == ipv6)
assert(FamilySIPAddress("sip:400471@[::1]")?.port == 5060)
assert(extensionAddress.matches(ipv6, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: ["2001:0db8::20"]))
assert(!extensionAddress.matches(ipv6, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: []))
assert(ipv6.matches(ipv6, providerHost: "[2001:db8::20]", providerPort: 5160, resolvedHosts: []))
assert(!extensionAddress.matches(FamilySIPAddress("sip:other@[2001:db8::20]:5160")!, providerHost: "premium.hamsoverip.com", providerPort: 5160, resolvedHosts: ["2001:db8::20"]))
for invalid in ["sip:u@[bad]", "sip:u@[::1", "sip:u@[::1]evil:5060", "sip:u@[::1]:", "sip:u@[::1]:0", "sip:u@[::1]:65536", "sip:u@::1", "sip:u@[::1]:+5060", "sip:u@[:::1]", "sip:u@[::1%lo0]"] {
    assert(FamilySIPAddress(invalid) == nil, "Accepted malformed IPv6 SIP address")
}
print("IPv6 caller identity canonicalization and exact approved-user matching passed")
