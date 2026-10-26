"""Basic functionality of every s6-dns and s6-networking program.

    python3 -I run.py PREFIX TLS ARCH

PREFIX is the MacPorts prefix the ports are installed in. TLS is "tls" for
s6-networking +openssl and "notls" for -openssl (which must then have no TLS
program at all). ARCH is "native", or "x86_64" to run every program under
Rosetta, from a universal build. responders.py must already be running.

Each check prints one line, "ok <name>: <what>" or "FAIL <name>: <why>";
the run ends with the count, and exits 1 on any failure. Everything is on
127.0.0.1, in a scratch directory removed at the end.
"""

import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

PREFIX, TLS, ARCH = sys.argv[1], sys.argv[2], sys.argv[3]
BIN = os.path.join(PREFIX, "bin")
PY = "/usr/bin/python3"
SCRATCH = tempfile.mkdtemp(prefix="s6net-test.")
failures = 0

DNS_ENV = {"DNSCACHEIP": "127.0.0.1"}

S6DNS = """skadnsd s6-randomip s6-dnsqualify s6-dnsip s6-dnsip4 s6-dnsip6 s6-dnsmx
s6-dnsname s6-dnsns s6-dnssoa s6-dnssrv s6-dnstxt s6-dnsip4-filter s6-dnsip6-filter
s6-dnsname-filter s6-dnsq s6-dnsqr s6-dns-hosts-compile""".split()
S6NET = """proxy-server s6-getservbyname s6-ident-client s6-tcpclient s6-tcpserver
s6-tcpserver-socketbinder s6-tcpserverd s6-tcpserver-access s6-clockadd s6-clockview
s6-sntpclock s6-taiclock s6-taiclockd""".split()
S6TLS = """s6-tlsclient s6-tlsc s6-tlsc-io s6-tlsserver s6-tlsd s6-tlsd-io
s6-ucspitlsc s6-ucspitlsd""".split()


def report(ok, name, detail):
    global failures
    if not ok:
        failures += 1
    print(f"{'ok' if ok else 'FAIL'} {name}: {detail}", flush=True)


def prog(p):
    """A program of the prefix, under Rosetta if ARCH asks."""
    path = os.path.join(BIN, p)
    return ["/usr/bin/arch", "-x86_64", path] if ARCH == "x86_64" else [path]


def run(argv, env=None, input=None, timeout=15):
    e = {"PATH": BIN + ":/usr/bin:/bin"}
    e.update(env or {})
    r = subprocess.run(argv, input=input, capture_output=True, env=e, timeout=timeout)
    return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")


def runb(argv, input=None, timeout=15):
    """run(), with stdout as raw bytes: the clock tools speak binary TAIN."""
    r = subprocess.run(argv, input=input, capture_output=True, env={"PATH": BIN + ":/usr/bin:/bin"}, timeout=timeout)
    return r.returncode, r.stdout, r.stderr.decode(errors="replace")


def check(name, argv, want, env=None, input=None, code=0):
    try:
        rc, out, err = run(argv, env, input)
    except subprocess.TimeoutExpired:
        report(False, name, "timed out")
        return ""
    ok = (rc != 0 if code == 'nonzero' else rc == code) and all(w in out for w in want)
    report(ok, name, f"exit {rc}, {out.strip()[:90]!r}" + ("" if ok else f", stderr {err.strip()[:120]!r}"))
    return out


def freeport():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def server(argv, env=None):
    """Start a server with -1: it prints its port once it's listening."""
    e = {"PATH": BIN + ":/usr/bin:/bin"}
    e.update(env or {})
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e, start_new_session=True)
    line = p.stdout.readline().decode().strip()
    return p, line


def stop(p, sig=signal.SIGTERM):
    if p.poll() is None:
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            pass
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()


def pyprog(code):
    path = os.path.join(SCRATCH, f"prog{abs(hash(code))}.py")
    with open(path, "w") as f:
        f.write(code)
    return [PY, "-I", path]


# Every program the variant installs, and none it doesn't.
def inventory():
    want = S6DNS + S6NET + (S6TLS if TLS == "tls" else [])
    missing = [p for p in want if not os.access(os.path.join(BIN, p), os.X_OK)]
    report(not missing, "inventory", f"{len(want)} programs present" if not missing else f"missing {missing}")
    if TLS == "notls":
        extra = [p for p in S6TLS if os.path.exists(os.path.join(BIN, p))]
        report(not extra, "inventory -openssl", "no TLS program installed" if not extra else f"unexpected {extra}")
    if ARCH == "x86_64":
        thin = [p for p in want if b"x86_64" not in subprocess.run(["/usr/bin/lipo", "-archs", os.path.join(BIN, p)], capture_output=True).stdout]
        report(not thin, "inventory universal", "every program has an x86_64 slice" if not thin else f"no x86_64 in {thin}")


def dns():
    check("s6-dnsip4", prog("s6-dnsip4") + ["a.s6test.example"], ["192.0.2.1"], DNS_ENV)
    check("s6-dnsip6", prog("s6-dnsip6") + ["a.s6test.example"], ["2001:db8::1"], DNS_ENV)
    check("s6-dnsip", prog("s6-dnsip") + ["a.s6test.example"], ["192.0.2.1", "2001:db8::1"], DNS_ENV)
    check("s6-dnsip -h", prog("s6-dnsip4") + ["-h", "localhost"], ["127.0.0.1"], {"DNSCACHEIP": "192.0.2.255"})
    check("s6-dnsip NXDOMAIN", prog("s6-dnsip4") + ["nope.s6test.example"], [], DNS_ENV, code=2)
    check("s6-dnsmx", prog("s6-dnsmx") + ["s6test.example"], ["10", "mx.s6test.example"], DNS_ENV)
    check("s6-dnsns", prog("s6-dnsns") + ["s6test.example"], ["ns1.s6test.example"], DNS_ENV)
    check("s6-dnssoa", prog("s6-dnssoa") + ["s6test.example"], ["ns1.s6test.example", "2026102601"], DNS_ENV)
    check("s6-dnssrv", prog("s6-dnssrv") + ["http", "tcp", "s6test.example"], ["a.s6test.example", "80"], DNS_ENV)
    check("s6-dnstxt", prog("s6-dnstxt") + ["s6test.example"], ["hello from s6test"], DNS_ENV)
    check("s6-dnstxt over TCP", prog("s6-dnstxt") + ["big.s6test.example"], ["x" * 200], DNS_ENV)
    check("s6-dnsname v4", prog("s6-dnsname") + ["192.0.2.1"], ["a.s6test.example"], DNS_ENV)
    check("s6-dnsname v6", prog("s6-dnsname") + ["2001:db8::1"], ["a.s6test.example"], DNS_ENV)
    check("s6-dnsq", prog("s6-dnsq") + ["a", "a.s6test.example", "127.0.0.1"], ["192.0.2.1"], DNS_ENV)
    check("s6-dnsqr", prog("s6-dnsqr") + ["aaaa", "a.s6test.example"], ["2001:db8::1"], DNS_ENV)
    check("s6-dnsqualify", prog("s6-dnsqualify") + ["a"], ["a.s6test.example"], {"DNSQUALIFY": "s6test.example"})
    # The filters resolve through the skadns library, which runs skadnsd.
    check("s6-dnsip4-filter (skadnsd)", prog("s6-dnsip4-filter"), ["a.s6test.example=192.0.2.1 rest"], DNS_ENV, b"a.s6test.example rest\n")
    check("s6-dnsip6-filter (skadnsd)", prog("s6-dnsip6-filter"), ["a.s6test.example=2001:db8::1 rest"], DNS_ENV, b"a.s6test.example rest\n")
    check("s6-dnsname-filter (skadnsd)", prog("s6-dnsname-filter"), ["192.0.2.1=a.s6test.example. rest"], DNS_ENV, b"192.0.2.1 rest\n")
    out = check("s6-randomip", prog("s6-randomip") + ["-4", "-n", "3"], ["."])
    report(len(out.split()) == 3, "s6-randomip count", f"{len(out.split())} addresses")
    hosts = os.path.join(SCRATCH, "hosts")
    with open(hosts, "w") as f:
        f.write("192.0.2.77 h1.s6test.example h1\n2001:db8::77 h1.s6test.example\n")
    check("s6-dns-hosts-compile", prog("s6-dns-hosts-compile") + ["-i", hosts, "-o", hosts + ".cdb"], [])
    report(os.path.getsize(hosts + ".cdb") > 2048, "s6-dns-hosts-compile output", f"{os.path.getsize(hosts + '.cdb')}-byte cdb")
    rc, out, err = run(prog("skadnsd"), DNS_ENV, input=b"")
    report(rc in (0, 1, 100, 111), "skadnsd standalone", f"exit {rc} on immediate EOF")


def tcp():
    check("s6-getservbyname", prog("s6-getservbyname") + ["http", "tcp"], ["80"])
    echoenv = pyprog("import os\nprint(os.environ['PROTO'], os.environ['TCPREMOTEIP'], os.environ['TCPLOCALPORT'], flush=True)\n")
    srv, port = server(prog("s6-tcpserver") + ["-1", "127.0.0.1", "0"] + echoenv)
    readenv = pyprog("import os\nprint(os.read(6, 200).decode().strip())\n")
    check("s6-tcpserver + s6-tcpclient", prog("s6-tcpclient") + ["127.0.0.1", port] + readenv, ["TCP 127.0.0.1 " + port])
    stop(srv)

    srv, port = server(prog("s6-tcpserver-socketbinder") + ["127.0.0.1", "0"] + prog("s6-tcpserverd") + ["-1"] + echoenv)
    check("s6-tcpserver-socketbinder + s6-tcpserverd", prog("s6-tcpclient") + ["127.0.0.1", port] + readenv, ["TCP 127.0.0.1 " + port])
    stop(srv)

    # -c 2: a third simultaneous client waits for a free slot.
    slow = pyprog("import time\nprint('in', flush=True)\ntime.sleep(2)\n")
    srv, port = server(prog("s6-tcpserver") + ["-1", "-c", "2", "127.0.0.1", "0"] + slow)
    socks, t0 = [], time.time()
    for _ in range(3):
        s = socket.create_connection(("127.0.0.1", int(port)))
        s.settimeout(5)
        socks.append(s)
    first = [s.recv(10) for s in socks[:2]]
    t_third = None
    try:
        if socks[2].recv(10):
            t_third = time.time() - t0
    except socket.timeout:
        pass
    report(all(b"in" in x for x in first) and t_third is not None and t_third > 1.5,
           "s6-tcpserver -c 2", f"third client served after {t_third and round(t_third, 1)} s, once a slot freed")
    for s in socks:
        s.close()
    stop(srv)

    # -C 1: unlike -c, a client over the per-address limit isn't queued: it's
    # accepted, logged as rejected and closed at once (s6-tcpserverd.c).
    srv, port = server(prog("s6-tcpserver") + ["-1", "-c", "10", "-C", "1", "127.0.0.1", "0"] + slow)
    a = socket.create_connection(("127.0.0.1", int(port)))
    a.settimeout(5)
    first = a.recv(10)
    b = socket.create_connection(("127.0.0.1", int(port)))
    b.settimeout(5)
    t0 = time.time()
    got = b.recv(10)
    t_b = time.time() - t0
    report(b"in" in first and got == b"" and t_b < 1, "s6-tcpserver -C 1",
           f"first client served; second from 127.0.0.1 closed after {round(t_b, 2)} s, prog not run")
    a.close(); b.close()
    stop(srv)

    # The signals, each against a connected, sleeping child.
    child = pyprog("import os, time\nprint(os.getpid(), flush=True)\ntime.sleep(30)\n")
    for sig, server_exits, child_dies in ((signal.SIGTERM, True, False), (signal.SIGHUP, False, True),
                                          (signal.SIGQUIT, True, True), (signal.SIGABRT, True, True)):
        srv, port = server(prog("s6-tcpserver") + ["-1", "127.0.0.1", "0"] + child)
        c = socket.create_connection(("127.0.0.1", int(port)))
        c.settimeout(5)
        cpid = int(c.recv(20).split()[0])
        os.kill(srv.pid, sig)
        time.sleep(1)
        s_gone = srv.poll() is not None
        try:
            os.kill(cpid, 0)
            c_gone = False
        except ProcessLookupError:
            c_gone = True
        report(s_gone == server_exits and c_gone == child_dies, f"s6-tcpserver {sig.name}",
               f"server {'exited' if s_gone else 'kept running'}, child {'gone' if c_gone else 'kept running'}")
        if not c_gone:
            os.kill(cpid, signal.SIGKILL)
        c.close()
        stop(srv)

    # s6-tcpserver-access: allow, then deny, by the filesystem rules.
    ok = pyprog("print('granted', flush=True)\n")
    for verdict, want in (("allow", "granted"), ("deny", "")):
        rules = os.path.join(SCRATCH, f"rules-{verdict}", "ip4", "127.0.0.1_32")
        os.makedirs(rules)
        open(os.path.join(rules, verdict), "w").close()
        srv, port = server(prog("s6-tcpserver") + ["-1", "127.0.0.1", "0"] + prog("s6-tcpserver-access")
                           + ["-i", os.path.dirname(os.path.dirname(rules))] + ok)
        c = socket.create_connection(("127.0.0.1", int(port)))
        c.settimeout(5)
        data = c.recv(50).decode()
        report((want in data) if want else data == "", f"s6-tcpserver-access {verdict}",
               f"{'prog ran' if data else 'connection closed, prog not run'}")
        c.close()
        stop(srv)

    # proxy-server: a PROXY v1 header sets the client's real addresses.
    pp = pyprog("import os, sys\nprint(os.environ['TCPREMOTEIP'], os.environ['TCPREMOTEPORT'], os.environ['TCPLOCALIP'], sys.stdin.readline().strip())\n")
    check("proxy-server v1", prog("proxy-server") + pp, ["198.51.100.7 40000 192.0.2.10 hello"],
          {"PROTO": "TCP", "TCPREMOTEIP": "127.0.0.1", "TCPREMOTEPORT": "1", "TCPLOCALIP": "127.0.0.1", "TCPLOCALPORT": "2"},
          b"PROXY TCP4 198.51.100.7 192.0.2.10 40000 443\r\nhello\n")

    check("s6-ident-client", prog("s6-ident-client") + ["127.0.0.1", "40000", "127.0.0.1", "80"], ["s6test"])


def clock():
    port = str(freeport())
    d = subprocess.Popen(prog("s6-taiclockd") + ["-i", "127.0.0.1", "-p", port], start_new_session=True)
    time.sleep(0.5)
    rc, adj, err = runb(prog("s6-taiclock") + ["-p", port, "127.0.0.1"])
    report(rc == 0 and len(adj) == 12, "s6-taiclockd + s6-taiclock", f"exit {rc}, {len(adj)}-byte TAIN adjustment" + ("" if rc == 0 else f", {err.strip()[:90]!r}"))
    rc2, view, _ = runb(prog("s6-clockview"), input=adj)
    view = view.decode(errors="replace")
    report(rc2 == 0 and "before:" in view and "after:" in view, "s6-clockview", f"exit {rc2}, {view.strip()[:90]!r}")
    # s6-clockadd parses the adjustment, then may not set the clock without
    # root: it must fail on that, cleanly, and the clock is never touched.
    rc3, _, err3 = runb(prog("s6-clockadd"), input=adj)
    report(rc3 == 111 and "set" in err3, "s6-clockadd (unprivileged)", f"exit {rc3}, {err3.strip()[:90]!r}")
    stop(d)
    rc, adj, err = runb(prog("s6-sntpclock") + ["-p", "12300", "127.0.0.1"])
    rc2, view, _ = runb(prog("s6-clockview"), input=adj)
    view = view.decode(errors="replace")
    report(rc == 0 and len(adj) == 12 and rc2 == 0 and "before:" in view, "s6-sntpclock", f"exit {rc}, view {view.strip()[:90]!r}" + ("" if rc == 0 else f", {err.strip()[:90]!r}"))


def tls():
    ssl = os.path.join(PREFIX, "bin", "openssl")
    k = lambda f: os.path.join(SCRATCH, f)
    subprocess.run([ssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "1",
                    "-subj", "/CN=s6test CA", "-keyout", k("ca.key"), "-out", k("ca.pem")], capture_output=True, check=True)
    subprocess.run([ssl, "req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-subj", "/CN=localhost",
                    "-keyout", k("srv.key"), "-out", k("srv.csr")], capture_output=True, check=True)
    with open(k("ext"), "w") as f:
        f.write("subjectAltName=DNS:localhost,IP:127.0.0.1\n")
    subprocess.run([ssl, "x509", "-req", "-in", k("srv.csr"), "-CA", k("ca.pem"), "-CAkey", k("ca.key"), "-CAcreateserial",
                    "-days", "1", "-extfile", k("ext"), "-out", k("srv.pem")], capture_output=True, check=True)
    subprocess.run([ssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "1",
                    "-subj", "/CN=other CA", "-keyout", k("other.key"), "-out", k("other.pem")], capture_output=True, check=True)
    senv = {"KEYFILE": k("srv.key"), "CERTFILE": k("srv.pem")}

    hello = pyprog("import sys\nsys.stdout.write('tls-hello ' + sys.stdin.readline())\nsys.stdout.flush()\n")
    srv, port = server(prog("s6-tlsserver") + ["-1", "127.0.0.1", "0"] + hello, senv)
    talk = pyprog("import os\nos.write(7, b'ping\\n')\nprint(os.read(6, 100).decode().strip())\n")
    check("s6-tlsserver + s6-tlsclient", prog("s6-tlsclient") + ["-k", "localhost", "127.0.0.1", port] + talk,
          ["tls-hello ping"], {"CAFILE": k("ca.pem")})
    check("s6-tlsclient refuses an unknown CA", prog("s6-tlsclient") + ["-k", "localhost", "127.0.0.1", port] + talk,
          [], {"CAFILE": k("other.pem")}, code="nonzero")
    stop(srv)

    # -K: a client that connects and never says a word. The handshake timer
    # must end the connection on time. How the engine ends is recorded, not
    # judged: it dies by SIGALRM (exit 142) rather than exiting 98 with
    # "handshake timed out", because stls_handshake.c's initializer names
    # both members of struct sigaction's handler union. Cosmetic, cross-
    # platform, upstream's, and not patched.
    e = {"PATH": BIN + ":/usr/bin:/bin"}
    e.update(senv)
    p = subprocess.Popen(prog("s6-tlsserver") + ["-v", "-K", "1000", "-1", "127.0.0.1", "0", "/bin/cat"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e, start_new_session=True)
    port = p.stdout.readline().decode().strip()
    c = socket.create_connection(("127.0.0.1", int(port)))
    c.settimeout(10)
    t0 = time.time()
    c.recv(10)
    waited = time.time() - t0
    c.close()
    time.sleep(0.5)
    stop(p)
    err = p.stderr.read().decode()
    ends = [l.split("exitcode ")[1].split()[0] for l in err.splitlines() if " end pid " in l and "exitcode" in l]
    report(len(ends) == 1 and 0.8 < waited < 3, "s6-tlsserver -K (handshake timeout)",
           f"closed after {waited:.1f} s, engine exit {ends}, {'with' if 'handshake timed out' in err else 'without'} its message")

    # STARTTLS-style: plaintext first, then each side asks for TLS on SSLCTLFD.
    sapp = pyprog(
        "import os, sys\n"
        "os.write(1, b'STARTTLS\\n')\n"
        "line = os.read(0, 100)\n"
        "os.write(int(os.environ['SSLCTLFD']), b'y')\n"
        "msg = os.read(int(os.environ['SSLREADFD']), 100)\n"
        "os.write(int(os.environ['SSLWRITEFD']), b'secure ' + msg)\n")
    capp = pyprog(
        "import os\n"
        "assert os.read(6, 100).startswith(b'STARTTLS')\n"
        "os.write(7, b'GO\\n')\n"
        "os.write(int(os.environ['SSLCTLFD']), b'y')\n"
        "os.write(int(os.environ['SSLWRITEFD']), b'hi\\n')\n"
        "print(os.read(int(os.environ['SSLREADFD']), 100).decode().strip())\n")
    srv, port = server(prog("s6-tcpserver") + ["-1", "127.0.0.1", "0"] + prog("s6-ucspitlsd") + sapp, senv)
    check("s6-ucspitlsd + s6-ucspitlsc", prog("s6-tcpclient") + ["127.0.0.1", port] + prog("s6-ucspitlsc") + ["-k", "localhost"] + capp,
          ["secure hi"], {"CAFILE": k("ca.pem")})
    stop(srv)


def arch_seen():
    """Under Rosetta, the programs the chains exec must run as x86_64 too."""
    if ARCH != "x86_64":
        return
    who = pyprog("import platform\nprint(platform.machine(), flush=True)\n")
    srv, port = server(prog("s6-tcpserver") + ["-1", "127.0.0.1", "0"] + who)
    out = check("chain architecture", prog("s6-tcpclient") + ["127.0.0.1", port] + pyprog("import os\nprint(os.read(6, 50).decode().strip())\n"), [""])
    report("x86_64" in out, "chain stays x86_64", f"the server's child ran as {out.strip()!r}")
    stop(srv)


try:
    print(f"# {PREFIX}, {TLS}, {ARCH}; host {platform.mac_ver()[0]} {platform.machine()}", flush=True)
    inventory()
    dns()
    tcp()
    clock()
    if TLS == "tls":
        tls()
    arch_seen()
finally:
    shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"# {failures} failure(s)")
sys.exit(1 if failures else 0)
