/* ISC license. */
/* Round-trip and overflow regressions for all three timeval converters. */
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <sys/time.h>
#include <skalibs/tai.h>

typedef int convert_func(struct timeval *, tain const *);

static int check(char const *name, convert_func *convert, int kind,
                 time_t seconds, unsigned int nano, int carry, long usec,
                 int overflow)
{
  tain input = TAIN_ZERO;
  struct timeval actual;
  if (kind == 0) tai_relative_from_time(&input.sec, seconds);
  else if (kind == 1)
  {
    if (!tai_from_time(&input.sec, seconds)) return 1;
  }
  else if (!tai_from_time_sysclock(&input.sec, seconds)) return 1;
  input.nano = nano;
  errno = 0;
  int result = convert(&actual, &input);
  int failed = overflow ? (result != 0 || errno != EOVERFLOW)
    : (result != 1 || actual.tv_sec != seconds + carry || actual.tv_usec != usec);
  printf("%s %s seconds=%" PRIdMAX " nano=%u%s\n",
         failed ? "FAIL" : "PASS", name, (intmax_t)seconds, nano,
         overflow ? " overflow" : "");
  return failed;
}

int main(void)
{
  struct {
    char const *name;
    convert_func *convert;
  } const functions[] = {
    { "relative", &timeval_from_tain_relative },
    { "absolute", &timeval_from_tain },
    { "sysclock", &timeval_sysclock_from_tain }
  };
  struct { unsigned int nano; int carry; long usec; } const cases[] = {
    { 0, 0, 0 }, { 499, 0, 0 }, { 500, 0, 1 },
    { 999999499, 0, 999999 }, { 999999500, 1, 0 }, { 999999999, 1, 0 }
  };
  time_t const seconds[] = { -2, -1, 0, 1, 42 };
  int failed = 0;
  for (int kind = 0; kind < 3; kind++)
  {
    for (unsigned int j = 0; j < sizeof seconds / sizeof seconds[0]; j++)
      for (unsigned int i = 0; i < sizeof cases / sizeof cases[0]; i++)
        failed += check(functions[kind].name, functions[kind].convert, kind,
                        seconds[j], cases[i].nano, cases[i].carry, cases[i].usec, 0);
    if ((time_t)-1 < 0 && sizeof(time_t) <= sizeof(uint64_t))
    {
      time_t maximum = (time_t)(((uint64_t)1 << (sizeof(time_t) * CHAR_BIT - 1)) - 1);
      failed += check(functions[kind].name, functions[kind].convert, kind,
                      -1, 999999500, 1, 0, 0);
      /* Absolute TAI's range is smaller than a signed 64-bit time_t's range. */
      if (kind == 0 || sizeof(time_t) < sizeof(uint64_t))
      {
        failed += check(functions[kind].name, functions[kind].convert, kind,
                        maximum, 999999499, 0, 999999, 0);
        failed += check(functions[kind].name, functions[kind].convert, kind,
                        maximum, 999999500, 0, 0, 1);
      }
    }
  }
  return failed ? 1 : 0;
}
