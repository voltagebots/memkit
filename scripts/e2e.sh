#!/usr/bin/env bash
# End-to-end smoke test: boots the real memkit binary and exercises every
# endpoint over HTTP, asserting the conflict-resolution behaviour. No external
# deps beyond curl + python3.
#
#   go build -o memkit ./cmd/memkit && ./scripts/e2e.sh
set -uo pipefail

PORT="${PORT:-8137}"
BASE="http://localhost:$PORT"
BIN="${BIN:-./memkit}"

[ -x "$BIN" ] || { echo "binary not found at $BIN — run: go build -o memkit ./cmd/memkit"; exit 1; }

MEMKIT_DB=":memory:" MEMKIT_API_KEYS="ka:acme,kb:other" "$BIN" --addr ":$PORT" >/tmp/memkit-e2e.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT

# Wait for liveness.
for _ in $(seq 1 50); do curl -sf "$BASE/healthz" >/dev/null 2>&1 && break; sleep 0.1; done

PASS=0; FAIL=0
jget() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null; }
assert() { # desc actual expected
  if [ "$2" = "$3" ]; then echo "  ok  $1"; PASS=$((PASS+1));
  else echo "FAIL  $1 — got [$2] want [$3]"; FAIL=$((FAIL+1)); fi
}
post()  { curl -s -XPOST   "$BASE$1" -H "Authorization: Bearer $2" -d "$3"; }
get()   { curl -s          "$BASE$1" -H "Authorization: Bearer $2"; }
put()   { curl -s -XPUT    "$BASE$1" -H "Authorization: Bearer $2" -d "$3"; }
del()   { curl -s -XDELETE "$BASE$1" -H "Authorization: Bearer $2"; }

echo "== health =="
assert "healthz ok" "$(get /healthz ka | jget "d['status']")" "ok"

echo "== remember + conflict resolution =="
R=$(post /v1/memories ka '{"user_id":"u1","content":"User works at Google as a backend engineer","category":"work"}')
assert "first fact → add" "$(echo "$R" | jget "d['action']")" "add"

R=$(post /v1/memories ka '{"user_id":"u1","content":"User works at OpenAI as a backend engineer","category":"work"}')
assert "contradiction → update" "$(echo "$R" | jget "d['action']")" "update"
assert "update sets superseded_id" "$(echo "$R" | jget "1 if d.get('superseded_id') else 0")" "1"

R=$(post /v1/memories ka '{"user_id":"u1","content":"User works at OpenAI as a backend engineer","category":"work"}')
assert "restatement → duplicate" "$(echo "$R" | jget "d['action']")" "duplicate"

echo "== search returns only the active fact =="
R=$(get "/v1/memories/search?user_id=u1&q=where+does+user+work" ka)
assert "search count = 1" "$(echo "$R" | jget "d['count']")" "1"
assert "active fact is OpenAI" "$(echo "$R" | jget "'OpenAI' in d['memories'][0]['content']")" "True"

echo "== categories =="
assert "one category 'work'" "$(get '/v1/memories/search?user_id=u1&q=x' ka >/dev/null; get '/v1/categories?user_id=u1' ka | jget "d['categories'][0]['name']")" "work"

echo "== explicit update + forget =="
R=$(post /v1/memories ka '{"user_id":"u2","content":"Deploy target is staging","category":"ops","resolve_conflicts":false}')
ID=$(echo "$R" | jget "d['id']")
R=$(put "/v1/memories/$ID" ka '{"content":"Deploy target is production"}')
assert "PUT → update" "$(echo "$R" | jget "d['action']")" "update"
NEWID=$(echo "$R" | jget "d['id']")
assert "forget active fact" "$(del "/v1/memories/$NEWID" ka | jget "d['ok']")" "True"

echo "== GDPR purge =="
post /v1/memories ka '{"user_id":"u3","content":"alpha","category":"a","resolve_conflicts":false}' >/dev/null
post /v1/memories ka '{"user_id":"u3","content":"beta","category":"b","resolve_conflicts":false}' >/dev/null
assert "purge removes all user rows" "$(del /v1/users/u3 ka | jget "d['removed']")" "2"

echo "== tenant isolation =="
post /v1/memories ka '{"user_id":"u1","content":"acme secret topology 10.0.0.1","category":"net"}' >/dev/null
assert "other tenant sees nothing" "$(get '/v1/memories/search?user_id=u1&q=topology' kb | jget "d['count']")" "0"

echo "== auth =="
assert "missing key → 401" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/v1/categories?user_id=u1")" "401"

echo "== heuristic boundary (no resolver) =="
post /v1/memories ka '{"user_id":"u4","content":"I love my job","category":"mood"}' >/dev/null
R=$(post /v1/memories ka '{"user_id":"u4","content":"I hate my job","category":"mood"}')
assert "short antonym → add (heuristic, needs resolver)" "$(echo "$R" | jget "d['action']")" "add"

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
