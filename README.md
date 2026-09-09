# PR #34539: downstream patch evidence

Review material for [MacPorts PR #34539](https://github.com/macports/macports-ports/pull/34539).
This independent evidence branch is **not part of the proposed MacPorts tree**.
The patch snapshots are the tested source changes; their headers in the PR may
also link here. Tests and documentation are AI-assisted, as disclosed in the PR.
No upstream acceptance or upstream submission is claimed.

## Result and boundaries

Test host: macOS 15.7.7 (24G720), Apple Silicon, Xcode 26.3, macOS SDK 26.2,
MacPorts 2.12.6. Testing uses a disposable, unprivileged MacPorts prefix with
its own registry. Builds use two jobs and reduced priority. StartupItem
installation/autostart are disabled. Nothing uses a live service directory.
The normal MacPorts builds select the installed macOS 15 SDK, as their logs
show; the separate availability reproduction explicitly uses the macOS 26 SDK.

Versions: skalibs 2.15.1.0, execline 2.9.9.2, s6 2.15.1.0, s6-rc 0.7.0.0.
All four revised Portfiles build and stage with `+universal` (arm64/x86_64).
The tests also use the previously installed, identically patched dependency
libraries in the disposable prefix. Fresh build-tree skalibs and s6 regressions
are recorded separately as `*-staged.log`.

| Correction | Negative control | Corrected result |
| --- | --- | --- |
| select read events | Ordinary readable pipe reports `0x11` (includes hangup) | `POLLIN` (`0x1`); readable/EOF, writable, deadline and descriptor cases pass |
| timeval rounding | Carry-boundary cases fail in all three original converters | Boundaries, negative/zero/positive seconds, relative signed-time maximum pass |
| SDK availability probe | SDK 26 build accepts unavailable standard spawn actions; runtime exits 139 on macOS 15 | Probe selects available `_np` actions; chdir and fchdir pass |
| s6-setlock descriptor | Original source with corrected dependencies fails all four fd 9 cases | 12 shared/exclusive, default/fd 3/fd 9, timed/blocking acquisition cases pass |
| Supervisor retirement | Pristine updater logs 14 `unable to chdir` errors over 30 updates plus transitions | 100 updates plus transitions, empty scanner log, native and x86_64 |
| Retirement before fdholder | Previous PR patch leaves the old idle supervisor alive after injected spawn failure, timeout, cancellation | Old supervisor exits, retained service PID survives, subsequent update succeeds |
| Rollback target | Injected failure before live-symlink switch deletes the active directory; subsequent update cannot open it | Original live target and PID survive; subsequent update succeeds |

`update-failures-previous.log` tests the original PR patch from commit
`60648eec4a878ce6f9f0d85ec281b37af81b04ec` against corrected support libraries.
`update-failures-final.log` and `update-failures-x86.log` test both new updater
corrections. Each has five cases: failure before the symlink switch, failure
before supervisor management, fdholder restart-spawn failure, fdholder timeout,
and cancellation at fdholder entry. The failure-before-management case keeps
the old idle supervisor intentionally: pruning while replacement links are
absent could terminate retained services. A subsequent normal update recovers.

The fault hook is compiled into **test-only binaries**. Production code has no
injection points, environment switches, delays, retries, or warning suppression.
The timeout hook expires the actual deadline and exercises the updater's exit-2
branch; the spawn hook exercises its exit-111 branch. Cancellation uses SIGSTOP
as a parent-observed barrier, followed by SIGTERM/SIGCONT. These are precise
boundary tests, not claims of coverage of every instruction or failure mode.

The live-update driver additionally covers preserved running PIDs, idle state,
rename, explicit restart, removal, longrun/oneshot conversion, addition, and
shutdown including essential services. x86_64 runs use extracted x86_64 slices
of the candidate s6-rc tools and core supervision tools under Rosetta, not native
Intel hardware. The rest of the disposable helper installation is universal.

Not established: crash-atomic updates, arbitrary interruption recovery, all
partial management rollbacks, process-death/PID-reuse races, completion of
retirement merely from a successful control-pipe write, or immunity to another
writer changing the scan directory. No live or global service/cache was used.
No native Intel, older macOS runtime, Tahoe runtime, privileged activation,
trace-mode install, or every-binary functionality claim is made.

## Why this ordering

`s6-rc-update` moves preserved service directories, switches the live symlink,
unlinks old scan entries, and links/manages replacement entries. Sending `xd`
to an old idle supervisor before the scanner has noticed its removal lets the
scanner reap it as active and attempt to restart it through a missing path.

The correction unlinks without sending `xd`. After replacement management
succeeds, it sends the existing `an` command **before** fdholder adjustment.
In s6-svscan, `a` sets the rescan deadline and the defer-killing bit (16);
`n` requests inactive-service retirement. Only a successful scan replaces the
active set and clears bit 16. Preserved directory device/inode identities stay
active; obsolete ones become inactive before retirement. Failed scans retain
the deferral. The existing control-write warning behavior is unchanged.

Separately, `make_new_livedir` stores the old path at offset 0 and the candidate
at `pos` in its string buffer. Successful commit correctly removes offset 0.
Rollback must instead remove `pos`, after restoring moved service directories.
The separate one-line patch corrects that target; it does not redesign rollback.

## Reproduction

Use a disposable local prefix and fresh verified source archives. Do not run
these tests against your normal services. Build/install the corrected dependency
stack into that prefix first, including s6-rc's libexec helpers. The live driver
also requires execline and GNU coreutils in the disposable dependency bin path.
It retains short `/tmp/s6rc.*` fixtures and shuts down its own scanner. The C
failure driver similarly retains `/tmp/rcfault.*` fixtures for inspection.

Archive SHA-256 values:

```
f9c905e74935c6fe911c7e344e3e89d5fbd2014c1a04650b524b15ce9b5635d1  skalibs-2.15.1.0.tar.gz
908ed4db3a6b3a23a205d8fd4cf2a71089156f2aeae0f54656045aafad2dee32  execline-2.9.9.2.tar.gz
eab9c46e22b66b16135f9a05ec68a0ea287d9060b84d10defaaa2caad158ab52  s6-2.15.1.0.tar.gz
bf5b8ce0da5a4ee70d642b818b61d9916a7a9b64a457595f388113e54a188688  s6-rc-0.7.0.0.tar.gz
```

The standalone C regressions build with `-std=c99 -Wall -Wextra -Werror`.
Link the three skalibs tests against the corresponding build-tree
`libskarnet.a.xyzzy` and headers, or the matching disposable prefix's
`libskarnet.a`. `test-setlock.c` needs only libc; invoke the resulting executable
by absolute path with the absolute path of the s6-setlock binary under test.
For a negative control, link original converter/select source ahead of the
corrected library, and compile original s6-setlock against corrected dependencies.

Run the live-update test as follows (replace placeholders with absolute paths):

```
DISPOSABLE/bin/execlineb -WS5 tests/test-live-update \
  RC_BINDIR UPDATE_BINARY DISPOSABLE/bin 100 RC_COMPILER
```

`RC_BINDIR` supplies s6-rc tools, `UPDATE_BINARY` selects pristine/previous/final,
and `RC_COMPILER` is the matching s6-rc-compile. Generated services use its
configured libexec prefix. For an uninstalled source build, either configure
that prefix to a disposable installed helper set, or build a test-only compiler
with `S6RC_EXTLIBEXECPREFIX` relocated to the build-tree helpers. Do not relocate
production artifacts merely for testing.

Build `tests/test-update-failures.c` with libc and POSIX.1-2008 declarations
(`-D_POSIX_C_SOURCE=200809L -D_DARWIN_C_SOURCE` on this host). Build
`tests/update-faults.c` with `-D_POSIX_C_SOURCE=200809L` and define
`UPDATER_SOURCE` as a quoted absolute filename of the updater source under test.
Supply the s6-rc build headers and matching disposable dependency headers; link
`libs6rc.a.xyzzy`, `libs6.a`, `libexecline.a`, `libskarnet.a` in that order.
Only the test translation unit interposes the four calls; libraries and the
normally built updater are unchanged. Then run:

```
PATH=RC_BINDIR:DISPOSABLE/bin:/usr/bin:/bin \
  /absolute/path/test-update-failures \
  /absolute/path/normal-final-updater /absolute/path/instrumented-updater
```

The first argument is used for post-failure recovery; the second injects the
failure into original/previous/final code. The prior patch and pristine updater
are available from the preserved original PR commit and verified release archive.
Use `-arch x86_64` and x86_64 slices of the candidate tools for the Rosetta run.

For the SDK test, configure pristine and patched skalibs with SDK 26 and deployment
target 15, build each library, and link/run `test-cspawn.c` against each. The
negative executable intentionally crashes on this host; disable core files in
the test process. `sdk26-*-configure.log` records the September 6 configure runs;
`sdk26-*-runtime.log` records their recheck on September 9. The two
`*-instrumented.log` files are also September 6 ASan/UBSan source-level checks,
not a new or whole-project sanitizer run. Other included logs are September 9.

## Downstream maintenance request

[MacPorts Guide 4.6.2](https://guide.macports.org/#development.patches.source)
says useful source patches should **generally** be sent to the application
developer, and documents carrying separate logical patches in `files/`.
That is not automatic permission to skip a reviewer's upstreaming request.

Skarnet's [skalibs](https://github.com/skarnet/skalibs/blob/main/CONTRIBUTING),
[s6](https://github.com/skarnet/s6/blob/main/CONTRIBUTING), and
[s6-rc](https://github.com/skarnet/s6-rc/blob/main/CONTRIBUTING) policies reject
LLM-generated contributions and prohibit bypassing that policy. These submissions
are therefore ineligible in their current form. No upstream PRs have been filed,
and no provenance is hidden. Upstream can of course independently fix a defect.

The request is for MacPorts to review these as explicitly maintained downstream
corrections, with tests kept outside its ports tree. The ISC license permits
modified distribution with its notice retained; licensing alone does not compel
MacPorts to accept a patch.

[Guide 7.3.3](https://guide.macports.org/#project.contributing) invites volunteers
for unmaintained ports, does not require commit access, and expects attention to
tickets, PRs, and debugging. The PR separately proposes `@bjornpagen openmaintainer`
for skalibs, execline, s6, and s6-rc. This is a maintainer offer pending acceptance,
not a claim of existing maintainer authority or exemption from review.
