/* ISC license. Isolated boundary tests; requires corrected s6/skalibs. */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void tick(void) { struct timespec t = { 0, 10000000 }; nanosleep(&t, 0); }

static pid_t spawn(char const *const *args, int output, int ready)
{
  pid_t p = fork();
  if (!p)
  {
    if (output >= 0 && (dup2(output, 1) < 0 || dup2(output, 2) < 0)) _exit(111);
    if (ready >= 0 && dup2(ready, 3) < 0) _exit(111);
    for (int fd = 4; fd < 256; fd++) close(fd);
    if (ready < 0) close(3);
    execvp(args[0], (char *const *)args);
    _exit(111);
  }
  return p;
}

static int waitfor(pid_t p, int options)
{
  int status;
  if (p <= 0) return 111;
  for (int i = 0; i < 1200; i++)
  {
    pid_t r = waitpid(p, &status, options | WNOHANG);
    if (r == p) return WIFEXITED(status) ? WEXITSTATUS(status)
      : WIFSTOPPED(status) ? 256 + WSTOPSIG(status) : 128 + WTERMSIG(status);
    if (r < 0 && errno != EINTR) return 111;
    tick();
  }
  fprintf(stderr, "child %ld did not finish within 12s\n", (long)p);
  return 112;
}

static int run(char const *const *args) { return waitfor(spawn(args, -1, -1), 0); }

static long number(char const *const *args)
{
  int p[2];
  char out[64] = {0};
  if (pipe(p)) return -1;
  pid_t pid = spawn(args, p[1], -1);
  close(p[1]);
  ssize_t n = read(p[0], out, sizeof out - 1);
  close(p[0]);
  if (waitfor(pid, 0) || n <= 0) return -1;
  return strtol(out, 0, 10);
}

static int gone(pid_t p)
{
  if (p <= 0) return 0;
  for (int i = 0; i < 300; i++)
  {
    if (kill(p, 0) < 0) return errno == ESRCH;
    tick();
  }
  return 0;
}

static int put(char const *path, char const *text)
{
  FILE *f = fopen(path, "w");
  if (!f) return 0;
  int ok = fputs(text, f) >= 0;
  return fclose(f) == 0 && ok;
}

static int service(char const *name)
{
  char path[256];
  snprintf(path, sizeof path, "source/%s", name);
  if (mkdir(path, 0700)) return 0;
  snprintf(path, sizeof path, "source/%s/type", name);
  if (!put(path, "longrun\n")) return 0;
  snprintf(path, sizeof path, "source/%s/run", name);
  if (!put(path, "#!/usr/bin/env execlineb\n/bin/sleep 600\n")) return 0;
  return chmod(path, 0700) == 0;
}

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); failed = 1; goto cleanup; } } while (0)

static int check(char const *updater, char const *instrumented, char const *mode)
{
  char root[] = "/tmp/rcfault.XXXXXX", live[256], db1[256], db2[256], db3[256];
  char scan[256], scanner_text[32], original[256], current[256];
  int failed = 0, pipefd[2] = {-1, -1}, logfd = -1;
  pid_t scanner = -1, updating = -1, oldidle = -1;
  long awake = -1;
  CHECK(mkdtemp(root));
  printf("CASE %s fixture=%s\n", mode, root); fflush(stdout);
  snprintf(live, sizeof live, "%s/live", root);
  snprintf(scan, sizeof scan, "%s/scan", root);
  snprintf(db1, sizeof db1, "%s/db1", root);
  snprintf(db2, sizeof db2, "%s/db2", root);
  snprintf(db3, sizeof db3, "%s/db3", root);
  CHECK(chdir(root) == 0 && mkdir("scan", 0700) == 0 && mkdir("source", 0700) == 0);
  CHECK(service("awake") && service("idle") && service("removed"));
  CHECK(run((char const *[]){"s6-rc-compile", db1, "source", 0}) == 0);
  CHECK(pipe(pipefd) == 0);
  logfd = open("supervision.log", O_WRONLY | O_CREAT | O_TRUNC, 0600);
  CHECK(logfd >= 0);
  scanner = spawn((char const *[]){"s6-svscan", "-d", "3", scan, 0}, logfd, pipefd[1]);
  CHECK(scanner > 0);
  close(pipefd[1]); pipefd[1] = -1;
  { char byte; CHECK(read(pipefd[0], &byte, 1) == 1); }
  close(pipefd[0]); pipefd[0] = -1;
  CHECK(run((char const *[]){"s6-rc-init", "-c", db1, "-l", live, "-t", "3000", scan, 0}) == 0);
  CHECK(run((char const *[]){"s6-rc", "-l", live, "-u", "change", "awake", "s6rc-fdholder", 0}) == 0);
  awake = number((char const *[]){"s6-svstat", "-o", "pid", "scan/awake", 0});
  snprintf(scanner_text, sizeof scanner_text, "%ld", (long)scanner);
  oldidle = number((char const *[]){"/usr/bin/pgrep", "-P", scanner_text, "-f", "^s6-supervise idle$", 0});
  CHECK(awake > 0 && oldidle > 0);
  ssize_t original_size = readlink(live, original, sizeof original - 1);
  CHECK(original_size > 0); original[original_size] = 0;
  CHECK(rename("source/removed", "removed-source") == 0);
  CHECK(run((char const *[]){"s6-rc-compile", db2, "source", 0}) == 0);
  CHECK(setenv("S6RC_TEST_FAULT", mode, 1) == 0);
  updating = spawn((char const *[]){instrumented, "-v", "2", "-t", "1500", "-l", live, db2, 0}, -1, -1);
  CHECK(updating > 0);
  if (!strcmp(mode, "cancel"))
  {
    CHECK(waitfor(updating, WUNTRACED) == 256 + SIGSTOP);
    CHECK(kill(updating, SIGTERM) == 0 && kill(updating, SIGCONT) == 0);
    CHECK(waitfor(updating, 0) == 128 + SIGTERM);
  }
  else CHECK(waitfor(updating, 0) == (!strcmp(mode, "timeout") ? 2 : 111));
  updating = -1;
  unsetenv("S6RC_TEST_FAULT");
  CHECK(kill(awake, 0) == 0);
  ssize_t current_size = readlink(live, current, sizeof current - 1);
  CHECK(current_size > 0); current[current_size] = 0;
  if (!strcmp(mode, "switch"))
  {
    CHECK(!strcmp(original, current));
    CHECK(kill(oldidle, 0) == 0);
  }
  else
  {
    CHECK(strcmp(original, current));
    if (!strcmp(mode, "manage")) CHECK(kill(oldidle, 0) == 0);
    else CHECK(gone(oldidle));
  }
  /* A fresh normal update must reconcile either retained live database. */
  CHECK(run((char const *[]){"s6-rc-compile", db3, "source", 0}) == 0);
  CHECK(run((char const *[]){updater, "-t", "4000", "-l", live, db3, 0}) == 0);
  CHECK(number((char const *[]){"s6-svstat", "-o", "pid", "scan/awake", 0}) == awake);
  CHECK(gone(oldidle));
  CHECK(run((char const *[]){"s6-rc", "-l", live, "diff", 0}) == 0);

cleanup:
  unsetenv("S6RC_TEST_FAULT");
  if (updating > 0) { kill(updating, SIGTERM); kill(updating, SIGCONT); waitfor(updating, 0); }
  if (scanner > 0)
  {
    /* Our scanner owns only this fixture; TERM also collects inactive children. */
    if (run((char const *[]){"s6-svscanctl", "-t", scan, 0}) || waitfor(scanner, 0)) failed = 1;
    struct stat st;
    if (fstat(logfd, &st) || st.st_size) { fprintf(stderr, "nonempty supervision.log\n"); failed = 1; }
  }
  if (logfd >= 0) close(logfd);
  if (pipefd[0] >= 0) close(pipefd[0]);
  if (pipefd[1] >= 0) close(pipefd[1]);
  printf("%s %s: retirement, retained PID, recovery; fixture retained\n", failed ? "FAIL" : "PASS", mode);
  return failed;
}

int main(int argc, char **argv)
{
  if (argc != 3 || argv[1][0] != '/' || argv[2][0] != '/') return 100;
  char const *modes[] = {"switch", "manage", "spawn", "timeout", "cancel"};
  int failures = 0;
  for (unsigned i = 0; i < sizeof modes / sizeof modes[0]; i++) failures += check(argv[1], argv[2], modes[i]);
  return failures ? 1 : 0;
}
