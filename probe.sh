#!/system/bin/sh
# Safe to run with the flashlight either on or off; performs no hardware writes.
MODDIR=${0%/*}
. "$MODDIR/lib/discovery.sh"
if [ "$1" = --output ] && [ -n "$2" ]; then
  umask 077
  OUT="$2.tmp.$$"
  trap 'rm -f "$OUT"' EXIT HUP INT TERM
  ht_discover > "$OUT" || exit 1
  mv -f "$OUT" "$2" || exit 1
else
  ht_discover
fi
