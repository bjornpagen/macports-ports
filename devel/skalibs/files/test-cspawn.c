/* ISC license. */
/* Ensure configured spawn directory actions are usable on the running OS. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <skalibs/cspawn.h>

static int check(char const *self, cspawn_fileaction const *action)
{
  char const *argv[] = { self, "--child", 0 };
  char const *envp[] = { 0 };
  pid_t pid = cspawn(self, argv, envp, 0, action, 1);
  if (!pid) { perror("cspawn"); return 1; }
  int status;
  pid_t result;
  do result = waitpid(pid, &status, 0); while (result < 0 && errno == EINTR);
  int failed = result != pid || !WIFEXITED(status) || WEXITSTATUS(status);
  printf("%s cspawn %s\n", failed ? "FAIL" : "PASS",
         action->type == CSPAWN_FA_CHDIR ? "chdir" : "fchdir");
  return failed;
}

int main(int argc, char **argv)
{
  if (argc == 2 && !strcmp(argv[1], "--child"))
  {
    struct stat current, root;
    if (stat(".", &current) < 0 || stat("/", &root) < 0) return 111;
    return current.st_dev != root.st_dev || current.st_ino != root.st_ino;
  }
  if (argv[0][0] != '/') return 100;
  alarm(5);
  int rootfd = open("/", O_RDONLY);
  if (rootfd < 0) return 111;
  cspawn_fileaction path = { .type = CSPAWN_FA_CHDIR, .x.path = "/" };
  cspawn_fileaction fd = { .type = CSPAWN_FA_FCHDIR, .x.fd = rootfd };
  int failed = check(argv[0], &path) + check(argv[0], &fd);
  close(rootfd);
  alarm(0);
  return failed ? 1 : 0;
}
