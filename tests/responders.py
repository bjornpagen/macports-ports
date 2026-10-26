"""Loopback responders for the s6-dns and s6-networking tests.

    sudo -k python3 -I responders.py USER READYFILE

s6-dns always queries port 53 and s6-ident-client always asks port 113, and
macOS lets only root bind those on 127.0.0.1. So this binds them as root, then
drops to USER before reading a single packet, and serves:

  127.0.0.1:53    UDP and TCP  DNS for the zone s6test.example (below); an
                               answer too big for UDP is truncated, so the
                               client must retry over TCP
  127.0.0.1:113   TCP          IDENT: every query is answered as user s6test
  127.0.0.1:12300 UDP          SNTPv4 server, from this machine's clock

READYFILE is written once everything is bound and privileges are dropped.
SIGTERM stops it. Nothing leaves loopback.
"""

import os
import pwd
import selectors
import signal
import socket
import struct
import sys
import time

ZONE = "s6test.example"
A, NS, SOA, PTR, MX, TXT, AAAA, SRV = 1, 2, 6, 12, 15, 16, 28, 33
BIG = ["x" * 200] * 4  # four 200-byte strings: over 512 bytes, so UDP truncates


def name(n):
    out = b""
    for label in n.rstrip(".").split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\0"


def ptr6(ip):
    full = socket.inet_pton(socket.AF_INET6, ip).hex()
    return ".".join(reversed(full)) + ".ip6.arpa"


RECORDS = {
    ("a." + ZONE, A): [socket.inet_aton("192.0.2.1")],
    ("a." + ZONE, AAAA): [socket.inet_pton(socket.AF_INET6, "2001:db8::1")],
    ("mx." + ZONE, A): [socket.inet_aton("192.0.2.25")],
    (ZONE, MX): [struct.pack(">H", 10) + name("mx." + ZONE)],
    (ZONE, NS): [name("ns1." + ZONE)],
    (ZONE, SOA): [name("ns1." + ZONE) + name("hostmaster." + ZONE)
                  + struct.pack(">IIIII", 2026102601, 3600, 600, 86400, 300)],
    (ZONE, TXT): [b"\x11hello from s6test"],
    ("big." + ZONE, TXT): [b"".join(bytes([len(s)]) + s.encode() for s in BIG)],
    ("_http._tcp." + ZONE, SRV): [struct.pack(">HHH", 10, 5, 80) + name("a." + ZONE)],
    ("1.2.0.192.in-addr.arpa", PTR): [name("a." + ZONE)],
    (ptr6("2001:db8::1"), PTR): [name("a." + ZONE)],
}
NAMES = {n for n, _ in RECORDS} | {"ns1." + ZONE, "hostmaster." + ZONE}


def answer(query, tcp):
    qid, flags, qd = struct.unpack(">HHH", query[:6])
    i, labels = 12, []
    while query[i]:
        labels.append(query[i + 1:i + 1 + query[i]].decode().lower())
        i += 1 + query[i]
    qname = ".".join(labels)
    qtype, qclass = struct.unpack(">HH", query[i + 1:i + 5])
    question = query[12:i + 5]
    rdatas = RECORDS.get((qname, qtype), [])
    rcode = 0 if qname in NAMES else 3
    rrs = b"".join(name(qname) + struct.pack(">HHIH", qtype, 1, 300, len(r)) + r for r in rdatas)
    rd = flags & 0x0100
    reply = struct.pack(">HHHHHH", qid, 0x8000 | 0x0400 | rd | 0x0080 | rcode, 1, len(rdatas), 0, 0) + question + rrs
    if not tcp and len(reply) > 512:
        reply = struct.pack(">HHHHHH", qid, 0x8000 | 0x0400 | 0x0200 | rd | 0x0080, 1, 0, 0, 0) + question
    return reply


def ntp(packet):
    now = time.time() + 2208988800
    stamp = struct.pack(">II", int(now), int((now % 1) * 2**32))
    origin = packet[40:48]
    return bytes([0x24, 1, 0, 0xEC]) + b"\0" * 8 + b"LOCL" + stamp + origin + stamp + stamp


def main():
    user, ready = sys.argv[1], sys.argv[2]
    udp53 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp53.bind(("127.0.0.1", 53))
    tcp53 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp53.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp53.bind(("127.0.0.1", 53))
    tcp53.listen(16)
    ident = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ident.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ident.bind(("127.0.0.1", 113))
    ident.listen(16)
    sntp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sntp.bind(("127.0.0.1", 12300))
    pw = pwd.getpwnam(user)
    os.setgroups([])
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with open(ready, "w") as f:
        f.write(f"{os.getpid()}\n")
    sel = selectors.DefaultSelector()
    for s in (udp53, tcp53, ident, sntp):
        sel.register(s, selectors.EVENT_READ)
    while True:
        for key, _ in sel.select():
            s = key.fileobj
            if s is udp53:
                data, peer = s.recvfrom(4096)
                s.sendto(answer(data, False), peer)
            elif s is sntp:
                data, peer = s.recvfrom(512)
                s.sendto(ntp(data), peer)
            elif s is tcp53:
                c, _ = s.accept()
                c.settimeout(5)
                with c:
                    size = struct.unpack(">H", c.recv(2))[0]
                    data = b""
                    while len(data) < size:
                        data += c.recv(size - len(data))
                    r = answer(data, True)
                    c.sendall(struct.pack(">H", len(r)) + r)
            elif s is ident:
                c, _ = s.accept()
                c.settimeout(5)
                with c:
                    line = c.recv(512).decode().strip()
                    c.sendall(f"{line} : USERID : UNIX : s6test\r\n".encode())


if __name__ == "__main__":
    main()
