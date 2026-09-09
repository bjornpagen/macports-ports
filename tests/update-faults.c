/* ISC license. Test-only interposition: never part of the packaged updater. */
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <skalibs/tai.h>
#include <skalibs/cspawn.h>
#include <skalibs/djbunix.h>
#include <skalibs/unix-transactional.h>
#include <s6/fdholder.h>
#include <s6-rc/s6rc-servicedir.h>

static int fault(char const *name)
{
  char const *s = getenv("S6RC_TEST_FAULT");
  return s && !strcmp(s, name);
}

static int test_switch(char const *a, char const *b, char *c, size_t d)
{
  if (fault("switch")) return (errno = EACCES, 0);
  return atomic_symlink4(a, b, c, d);
}

static int test_manage(char const *a, char const *b, tain const *c, tain *d)
{
  /* Failure before link creation, not a simulation of every partial rollback. */
  if (fault("manage")) return (errno = EACCES, -1);
  return s6rc_servicedir_manage(a, b, c, d);
}

static int test_fdholder(s6_fdholder_t *a, char const *b, tain const *c, tain *d)
{
  if (fault("cancel"))
  {
    /* Parent observes this stop with waitpid(WUNTRACED), then cancels us. */
    raise(SIGSTOP);
    for (;;) pause();
  }
  if (fault("timeout"))
  {
    struct timespec tick = { 0, 1000000 };
    while (tain_less(d, c)) { nanosleep(&tick, 0); tain_now(d); }
    return (errno = ETIMEDOUT, 0);
  }
  if (fault("spawn")) return (errno = ECONNREFUSED, 0);
  return s6_fdholder_start(a, b, c, d);
}

static pid_t test_spawn(char const *file, char const *const *argv,
  char const *const *envp, unsigned int flags, cspawn_fileaction const *fa, size_t n)
{
  if (!strcmp(file, "s6-svc") && fault("spawn")) return (errno = EAGAIN, 0);
  if (!strcmp(file, "s6-svc") && fault("timeout"))
  {
    /* Let the real updater's wait/expired-deadline branch run deterministically. */
    char const *args[] = { "/usr/bin/true", 0 };
    return cspawn(args[0], args, envp, flags, fa, n);
  }
  return cspawn(file, argv, envp, flags, fa, n);
}

#define atomic_symlink4 test_switch
#define s6rc_servicedir_manage test_manage
#define s6_fdholder_start test_fdholder
#define cspawn test_spawn
#include UPDATER_SOURCE
