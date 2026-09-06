/* ISC license. */
/* Synchronize through pipes: a contender only runs after the holder execs. */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static int status_of(pid_t pid)
{
  int status;
  pid_t r;
  do r = waitpid(pid, &status, 0); while (r < 0 && errno == EINTR);
  return r == pid && WIFEXITED(status) ? WEXITSTATUS(status) : 111;
}

static int contend(char const *binary, char const *self, char const *file,
                   char const *mode, int timed)
{
  pid_t pid = fork();
  if (pid < 0) { perror("fork"); exit(111); }
  if (!pid)
  {
    int nullfd = open("/dev/null", O_WRONLY);
    if (nullfd < 0 || dup2(nullfd, 2) < 0) _exit(111);
    if (nullfd != 2) close(nullfd);
    alarm(3);
    if (timed) execl(binary, binary, mode, "-t", "50", file, self, "--success", (char *)0);
    else execl(binary, binary, mode, "-n", file, self, "--success", (char *)0);
    _exit(111);
  }
  return status_of(pid);
}

static int check(char const *binary, char const *self, char const *file,
                 char const *dest, char const *mode)
{
  int ready[2], release[2], failed = 0;
  char byte;
  if (pipe(ready) < 0 || pipe(release) < 0) { perror("pipe"); exit(111); }
  pid_t holder = fork();
  if (holder < 0) { perror("fork"); exit(111); }
  if (!holder)
  {
    if (dup2(release[0], 0) < 0 || dup2(ready[1], 1) < 0) _exit(111);
    close(ready[0]); close(ready[1]); close(release[0]); close(release[1]);
    alarm(5);
    if (dest)
      execl(binary, binary, mode, "-d", dest, file, self, "--holder", dest, (char *)0);
    else
      execl(binary, binary, mode, file, self, "--holder", (char *)0);
    _exit(111);
  }
  close(ready[1]); close(release[0]);
  ssize_t n;
  do n = read(ready[0], &byte, 1); while (n < 0 && errno == EINTR);
  close(ready[0]);
  if (n != 1 || byte != 'R') failed = 1;
  else
  {
    failed += contend(binary, self, file, "-w", 0) != 1;
    failed += contend(binary, self, file, "-r", 0) != (!strcmp(mode, "-w") ? 1 : 0);
    failed += contend(binary, self, file, "-w", 1) != 1;
  }
  /* EOF releases the holder even when an assertion failed. */
  close(release[1]);
  failed += status_of(holder) != 0;
  failed += contend(binary, self, file, "-w", 0) != 0;
  printf("%s %s descriptor=%s: exclusion, timeout, release\n",
         failed ? "FAIL" : "PASS", mode, dest ? dest : "default");
  return failed;
}

int main(int argc, char **argv)
{
  if (argc >= 2 && !strcmp(argv[1], "--holder"))
  {
    char byte;
    ssize_t n;
    alarm(5);
    if (argc == 3 && fcntl(atoi(argv[2]), F_GETFD) < 0) return 111;
    if (write(1, "R", 1) != 1) return 111;
    do n = read(0, &byte, 1); while (n < 0 && errno == EINTR);
    return n == 0 ? 0 : 111;
  }
  if (argc == 2 && !strcmp(argv[1], "--success")) return 0;
  if (argc != 2 || argv[0][0] != '/' || argv[1][0] != '/') return 100;
  char file[] = "test-setlock.XXXXXX";
  int fd = mkstemp(file), failed = 0;
  if (fd < 0) { perror("mkstemp"); return 111; }
  close(fd);
  char const *const destinations[] = { 0, "3", "9" };
  for (unsigned int i = 0; i < sizeof destinations / sizeof destinations[0]; i++)
  {
    failed += check(argv[1], argv[0], file, destinations[i], "-w");
    failed += check(argv[1], argv[0], file, destinations[i], "-r");
  }
  if (unlink(file) < 0) { perror("unlink"); return 111; }
  return failed ? 1 : 0;
}
