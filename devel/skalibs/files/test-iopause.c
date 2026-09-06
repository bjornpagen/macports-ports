/* ISC license. */
/* Regression tests for the select backend; no threads or external services. */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <unistd.h>
#include <skalibs/iopause.h>
#include <skalibs/tai.h>

static int check(char const *name, int fd, tain const *deadline, tain const *stamp,
                 int events, int expected_result, int expected_events, int expected_errno)
{
  iopause_fd event = { .fd = fd, .events = events, .revents = -1 };
  errno = 0;
  int result = iopause_select(&event, 1, deadline, stamp);
  int error = errno;
  int failed = result != expected_result || event.revents != expected_events
    || (result < 0 && error != expected_errno);
  printf("%s %s: result=%d revents=%#x errno=%d (%s)\n",
         failed ? "FAIL" : "PASS", name, result, event.revents, error, strerror(error));
  return failed;
}

int main(void)
{
  int p[2], failed = 0;
  tain stamp = TAIN_EPOCH;
  tain finite = stamp;
  tain fractional = stamp;
  tain past = stamp;
  tain large = stamp;
  char byte;
  /* A broken timeout implementation must not hang the regression process. */
  alarm(5);
  if (pipe(p) < 0 || write(p[1], "x", 1) != 1) return 111;
  tain_addsec(&finite, &stamp, 1);
  failed += check("finite/readable", p[0], &finite, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  failed += check("NULL/infinite", p[0], 0, 0, IOPAUSE_READ, 1, POLLIN, 0);
  failed += check("TAIN_INFINITE", p[0], &tain_infinite, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  large.sec.x += 100000001;
  failed += check("large-finite", p[0], &large, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  failed += check("expired-infinite-sentinel", p[0], &tain_infinite, &tain_infinite, IOPAUSE_READ, 1, POLLIN, 0);
  fractional.nano = 999999499;
  failed += check("before-rounding-boundary", p[0], &fractional, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  fractional.nano = 999999500;
  failed += check("at-rounding-boundary", p[0], &fractional, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  fractional.nano = 999999999;
  failed += check("after-rounding-boundary", p[0], &fractional, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  failed += check("writable", p[1], &finite, &stamp, IOPAUSE_WRITE, 1, POLLOUT, 0);
  if (read(p[0], &byte, 1) != 1) return 111;
  failed += check("due/empty", p[0], &stamp, &stamp, IOPAUSE_READ, 0, 0, 0);
  past.sec.x--;
  failed += check("past/empty", p[0], &past, &stamp, IOPAUSE_READ, 0, 0, 0);
  fractional = stamp;
  fractional.nano = 10000000;
  failed += check("finite/empty", p[0], &fractional, &stamp, IOPAUSE_READ, 0, 0, 0);
  failed += check("negative-fd/ignored", -1, &stamp, &stamp, IOPAUSE_READ, 0, 0, 0);
  failed += check("oversized-fd/rejected", FD_SETSIZE, &stamp, &stamp, IOPAUSE_READ, -1, 0, EMFILE);
  close(p[1]);
  failed += check("EOF/is-readable", p[0], &finite, &stamp, IOPAUSE_READ, 1, POLLIN, 0);
  close(p[0]);
  alarm(0);
  return failed ? 1 : 0;
}
