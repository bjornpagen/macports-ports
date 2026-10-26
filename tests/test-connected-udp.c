/* What Darwin does with a connected UDP socket, the three facts the
   s6-networking clock patch rests on:
     1. sendto() naming the connected peer fails with EISCONN;
     2. write() (no address) sends to the peer;
     3. a datagram from any other sender never reaches the socket.
   cc -Wall -o test-connected-udp test-connected-udp.c && ./test-connected-udp
   Exits 0 if all three hold. */

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int udp (void)
{
  int s = socket(AF_INET, SOCK_DGRAM, 0) ;
  struct sockaddr_in a = { .sin_family = AF_INET } ;
  inet_pton(AF_INET, "127.0.0.1", &a.sin_addr) ;
  bind(s, (struct sockaddr *)&a, sizeof a) ;
  return s ;
}

static struct sockaddr_in addr (int s)
{
  struct sockaddr_in a ;
  socklen_t n = sizeof a ;
  getsockname(s, (struct sockaddr *)&a, &n) ;
  return a ;
}

int main (void)
{
  int server = udp(), stranger = udp(), client = udp(), fails = 0 ;
  struct sockaddr_in sa = addr(server), ca ;
  char c ;
  connect(client, (struct sockaddr *)&sa, sizeof sa) ;
  ca = addr(client) ;

  ssize_t r = sendto(client, "a", 1, 0, (struct sockaddr *)&sa, sizeof sa) ;
  int e = errno ;
  printf("%s 1. sendto(connected peer): %zd, %s\n", r == -1 && e == EISCONN ? "ok" : "FAIL", r, r < 0 ? strerror(e) : "sent") ;
  fails += !(r == -1 && e == EISCONN) ;

  r = write(client, "b", 1) ;
  e = errno ;
  printf("%s 2. write(): %zd, %s\n", r == 1 ? "ok" : "FAIL", r, r < 0 ? strerror(e) : "sent") ;
  fails += r != 1 ;

  sendto(stranger, "x", 1, 0, (struct sockaddr *)&ca, sizeof ca) ;
  sendto(server, "y", 1, 0, (struct sockaddr *)&ca, sizeof ca) ;
  usleep(100000) ;
  fcntl(client, F_SETFL, O_NONBLOCK) ;
  char got[8] = "" ;
  size_t n = 0 ;
  while (n < sizeof got - 1 && read(client, &c, 1) == 1) got[n++] = c ;
  printf("%s 3. client read \"%s\" (stranger sent x, server sent y)\n", !strcmp(got, "y") ? "ok" : "FAIL", got) ;
  fails += !!strcmp(got, "y") ;
  return !!fails ;
}
