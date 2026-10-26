# s6-dns and s6-networking: MacPorts submission evidence

Review material for the MacPorts pull request adding `net/s6-dns` 2.4.1.3 and
`net/s6-networking` 2.8.0.1. This independent evidence branch is **not part of
the proposed MacPorts tree**. The tests and this document are AI-assisted, as
disclosed in the pull request. No upstream acceptance or upstream submission is
claimed.

## Result and boundaries

Test host: macOS 27.0.1 (26A434), Apple Silicon (arm64), Xcode 27.1, macOS 27.0
SDK, MacPorts 2.12.7. Testing uses a disposable, unprivileged MacPorts prefix
built from the 2.12.7 release (SHA-256 checked against its published `.chk.txt`),
with its own registry, this branch's ports tree as its only source, two build
jobs at reduced priority, and no StartupItems. Nothing touches the host's
MacPorts installation or any live service.

The only privileged step is `tests/responders.py`: s6-dns always queries port 53
and `s6-ident-client` always asks port 113, and macOS lets only root bind those on
127.0.0.1. It binds them under `sudo`, then drops to the invoking user before
reading a packet. Every test is on 127.0.0.1.

| Build | Result |
| --- | --- |
| `s6-dns` | 18 programs, static libraries, headers, `.pc` files, docs; links only `libSystem`; no compiler warnings |
| `s6-networking +openssl` (default), unpatched | 42/46: every check passes but the four clock checks; `s6-taiclock` and `s6-sntpclock` fail every round trip with `EISCONN` (`logs/test-openssl-native-pristine.log`) |
| `s6-networking +openssl`, with `patch-clock-connected-send.diff` | 46/46 (`logs/test-openssl-native-patched.log`) |
| `s6-networking -openssl`, patched | 43/43: 31 programs, no TLS program, only `libs6net` (`logs/test-noopenssl-native.log`) |

`tests/test-connected-udp.c` reproduces, on its own, the Darwin socket behaviour
the patch rests on (`logs/test-connected-udp.log`).

**Not established:** `+universal`, x86_64 and native Intel hardware; macOS releases other than 27.0.1; trace mode (`port -t`), which on
macOS 27 kills every build tool because `darwintrace.dylib` has no `arm64e`
slice (see "Trace mode"); a privileged install; MacPorts CI.

## The clock patch

`s6-taiclock` and `s6-sntpclock` `connect()` their UDP socket to the server, then
send each query with skalibs' `socket_sendnb46_g`: `sendto()` naming that same
server again. POSIX lets a connected connectionless socket either honour or
refuse such a destination (`sendto()`, IEEE Std 1003.1-2024; EISCONN is a "may
fail" error). Linux honours it (`udp_sendmsg()`, `net/ipv4/udp.c`, v7.3). XNU
refuses it: `udp_output()` (`bsd/netinet/udp_usrreq.c`) returns `EISCONN` for any
destination once the socket has a foreign address, even the connected peer, and
`udp6_output()` does the same. The check is unchanged from xnu-1504.15.3 (10.6)
through xnu-12377.121.6.

The patch keeps the `connect()` (it is what makes the kernel drop datagrams from
any other sender; the programs discard `recvfrom()`'s source address) and sends
with skalibs' `timed_write()`, which takes no address. `test-connected-udp.c`
shows the three facts: `sendto()` to the connected peer fails with `EISCONN`,
`write()` sends, and a stranger's datagram never reaches the connected socket.

## Not patched

`stls_handshake.c` initializes both `.sa_handler` and `.sa_sigaction`, which name
one union member on Darwin (and glibc), so the `-K` handshake timer kills
`s6-tlsd-io`/`s6-tlsc-io` with SIGALRM (exit 142) instead of exiting 98 with
"handshake timed out". The timeout still ends the connection on time (checked).
The difference is the exit status and message only, it is not Darwin-specific,
and it is left to upstream.

## Trace mode

MacPorts' trace mode injects `darwintrace.dylib`, built `x86_64 arm64`, into every
build tool. macOS 27's system tools run as `arm64e`, and dyld refuses the
library: "missing compatible architecture (have 'x86_64,arm64', need 'arm64e')".
Every `port -t` build fails at its first extract, for any port. This is a MacPorts
base limitation (compare Trac #60818), independent of these ports.

## Reproduction

1. Build a disposable MacPorts prefix (`./configure --prefix=$P
   --with-no-root-privileges --without-startupitems`), point its `sources.conf`
   at a checkout of this pull request's branch, and run `portindex` there.
2. `port -vs install s6-networking` (and `-openssl`).
3. In one terminal: `sudo -k python3 -I tests/responders.py $USER READYFILE`.
4. `python3 -I tests/run.py $P tls native` (or `notls`).
5. `cc -Wall -o t tests/test-connected-udp.c && ./t`.

## Files

| File | What |
| --- | --- |
| `tests/run.py` | every program of both ports, on loopback; one `ok`/`FAIL` line per check |
| `tests/responders.py` | DNS (UDP and TCP, zone `s6test.example`), IDENT and SNTP responders on 127.0.0.1 |
| `tests/test-connected-udp.c` | the Darwin connected-UDP behaviour, on its own |
| `logs/test-openssl-native-pristine.log` | `+openssl` without the patch: the negative control |
| `logs/test-openssl-native-patched.log` | `+openssl` with the patch |
| `logs/test-noopenssl-native.log` | `-openssl` with the patch |
| `logs/test-connected-udp.log` | the reproducer's run |
| `logs/port-*.log` | the `port -vs install` logs: each port's own phases (the unpatched build's from the same Portfile without its `patchfiles` line) |
