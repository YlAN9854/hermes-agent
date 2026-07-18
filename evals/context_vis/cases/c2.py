"""Case c2: memory-leak hunt in a Node.js websocket service.

Arc: reproduce -> hypothesis A (listeners) abandoned -> hypothesis B (cache)
partial fix -> return to hypothesis A with heap-diff evidence -> real fix ->
verification. English, ~50 turns.
"""
from evals.context_vis.case_schema import Case, T, Segment, GoldConstraint, Backtrack

TURNS = [
    # ------------------------------------------------------------------
    # Segment 0: reproduce the leak (turns 0-9)
    # ------------------------------------------------------------------
    T("user",
      "Our ws-gateway service (Node 20, plain `ws` library) is leaking memory in "
      "production. RSS climbs roughly 40 MB per hour under normal traffic and the "
      "pods OOM about every two days. Kubernetes keeps restarting them, which hides "
      "the problem from most dashboards. I want to find the actual leak. Two ground "
      "rules: do not restart the production pods while we debug — we need the live "
      "heap state intact in case we have to snapshot a real pod, and clone the repo "
      "locally so we can reproduce there first."),
    T("assistant",
      "Understood — no production restarts; we keep the live pods as forensic "
      "evidence and reproduce locally instead. Plan:\n"
      "1. Look at the repo layout to see where connections are handled.\n"
      "2. Build a small churn load test (connect, chat, disconnect in a loop).\n"
      "3. Run the server with --inspect, watch RSS, and capture heap snapshots "
      "before/after load so we have a baseline diff.\n"
      "Let me start with the layout."),
    T("tool",
      "$ ls -R src/\n"
      "src/:\n"
      "server.js  connection.js  cache.js  metrics.js  router.js\n"
      "src/helpers:\n"
      "heartbeat.js  auth.js  backoff.js\n"
      "test/:\n"
      "connection.test.js  router.test.js  cache.test.js\n"
      "$ wc -l src/*.js src/helpers/*.js\n"
      "  212 src/server.js\n"
      "  148 src/connection.js\n"
      "   64 src/cache.js\n"
      "   88 src/metrics.js\n"
      "  131 src/router.js\n"
      "   47 src/helpers/heartbeat.js\n"
      "   93 src/helpers/auth.js\n"
      "   31 src/helpers/backoff.js",
      tool_name="bash"),
    T("assistant",
      "Small codebase — server.js accepts sockets, connection.js wraps each socket, "
      "cache.js and heartbeat.js are the obvious stateful helpers. I'll write "
      "loadtest.js: 500 concurrent clients, each connects, sends 20 messages, "
      "disconnects, reconnects — constant churn is what production sees. Then run "
      "the server locally with --inspect and sample RSS every 30 seconds."),
    T("tool",
      "$ node --inspect=9229 src/server.js & node tools/loadtest.js --clients 500 --churn\n"
      "Debugger listening on ws://127.0.0.1:9229/2f8a1c\n"
      "loadtest: 500 clients, churn mode, msg rate 10/s per client\n"
      "t=0s    rss=96.4 MB  heapUsed=41.2 MB  conns=500\n"
      "t=30s   rss=131.8 MB heapUsed=63.0 MB  conns=500\n"
      "t=60s   rss=168.1 MB heapUsed=84.9 MB  conns=500\n"
      "t=120s  rss=231.5 MB heapUsed=127.6 MB conns=500\n"
      "t=180s  rss=294.2 MB heapUsed=169.8 MB conns=500\n"
      "t=240s  rss=357.9 MB heapUsed=212.3 MB conns=500\n"
      "t=300s  rss=422.6 MB heapUsed=255.1 MB conns=500",
      tool_name="bash"),
    T("assistant",
      "Reproduced cleanly: ~65 MB RSS growth per minute of churn at this intensity, "
      "and heapUsed tracks it, so this is a JS-heap leak, not native buffers or "
      "fragmentation. Connection count stays at 500, so we're retaining state for "
      "sockets that already disconnected. Capturing a baseline snapshot now, then "
      "another after five more minutes of churn."),
    T("tool",
      "$ node tools/snapshot.js --port 9229 --out baseline.heapsnapshot\n"
      "wrote baseline.heapsnapshot (48.2 MB)\n"
      "$ sleep 300 && node tools/snapshot.js --port 9229 --out after.heapsnapshot\n"
      "wrote after.heapsnapshot (287.4 MB)\n"
      "$ node tools/heapdiff.js baseline.heapsnapshot after.heapsnapshot --top 6\n"
      "constructor         #delta      size-delta\n"
      "(closure)           +311,208    +38.1 MB\n"
      "(string)            +288,940    +91.7 MB\n"
      "Object              +154,102    +19.9 MB\n"
      "WebSocket           +14,382     +33.4 MB\n"
      "Array               +96,511     +12.2 MB\n"
      "Timeout             +14,377     +2.6 MB",
      tool_name="bash"),
    T("assistant",
      "The diff is telling: +14,382 WebSocket objects retained after five minutes of "
      "churn — those sockets closed but never got collected. Alongside them: a huge "
      "pile of closures and strings, plus ~14k Timeout objects, almost 1:1 with the "
      "leaked sockets. Two candidate explanations:\n"
      "A) An event-listener leak — handlers registered per connection and never "
      "removed, keeping the socket reachable.\n"
      "B) An unbounded cache — the strings could be message payloads pinned in some "
      "Map keyed per message or per socket."),
    T("user",
      "Good, that matches what production graphs implied. One process rule before we "
      "start changing anything: always run the soak test for at least 10 minutes "
      "before calling it fixed — we've been burned by 2-minute 'fixes' before. "
      "Start with the listener theory, that's bitten us in other services."),
    T("assistant",
      "Agreed on the 10-minute soak bar. Starting on hypothesis A: I'll inventory "
      "every .on()/.addListener() registration in src/, check each has a matching "
      "removal on the close path, and instrument the server to log listener counts "
      "on the main emitters while the churn test runs."),

    # ------------------------------------------------------------------
    # Segment 1: hypothesis A — event-listener leak (turns 10-19)
    # ------------------------------------------------------------------
    T("tool",
      "$ grep -rn \"\\.on(\\|addListener(\" src/ | grep -v test\n"
      "src/server.js:41:  wss.on('connection', (socket, req) => {\n"
      "src/server.js:58:  wss.on('error', onServerError);\n"
      "src/server.js:73:  process.on('SIGTERM', shutdown);\n"
      "src/connection.js:22:    socket.on('message', this.onMessage);\n"
      "src/connection.js:23:    socket.on('close', this.onClose);\n"
      "src/connection.js:24:    socket.on('error', this.onError);\n"
      "src/router.js:17:  bus.on('broadcast', fanout);\n"
      "src/helpers/heartbeat.js:19:    socket.on('pong', onPong);\n"
      "src/helpers/auth.js:30:  socket.on('message', firstMessageAuth);",
      tool_name="grep"),
    T("assistant",
      "Nine registration sites. The per-connection ones in connection.js are the "
      "likely suspects — if onClose doesn't tear them down, every churned socket "
      "leaves three live handlers behind. Let me read the Connection class and its "
      "close path before instrumenting anything."),
    T("tool",
      "src/connection.js (lines 18-44):\n"
      "  constructor(socket, ctx) {\n"
      "    this.socket = socket;\n"
      "    this.ctx = ctx;\n"
      "    socket.on('message', this.onMessage);\n"
      "    socket.on('close', this.onClose);\n"
      "    socket.on('error', this.onError);\n"
      "    startHeartbeat(socket);\n"
      "  }\n"
      "  onClose = () => {\n"
      "    this.socket.removeListener('message', this.onMessage);\n"
      "    this.socket.removeListener('error', this.onError);\n"
      "    this.ctx.registry.delete(this.id);\n"
      "    metrics.gauge('conns', this.ctx.registry.size);\n"
      "  };",
      tool_name="read_file"),
    T("assistant",
      "The Connection class itself looks disciplined: onClose removes 'message' and "
      "'error' (the 'close' listener is fine to leave, the socket is done). Registry "
      "delete is there too. To be rigorous I'll add instrumentation that logs "
      "listenerCount for the server-level emitters every 15 seconds during churn — "
      "if handlers accumulate anywhere central we'll see the counts climb."),
    T("tool",
      "$ node src/server.js --debug-listeners & node tools/loadtest.js --clients 500 --churn --duration 600\n"
      "listeners t=15s  wss:{connection:1,error:1} bus:{broadcast:1} process:{SIGTERM:1}\n"
      "listeners t=120s wss:{connection:1,error:1} bus:{broadcast:1} process:{SIGTERM:1}\n"
      "listeners t=300s wss:{connection:1,error:1} bus:{broadcast:1} process:{SIGTERM:1}\n"
      "listeners t=600s wss:{connection:1,error:1} bus:{broadcast:1} process:{SIGTERM:1}\n"
      "loadtest done: 500 clients, 61,940 connect/disconnect cycles, 0 errors",
      tool_name="bash"),
    T("assistant",
      "Ten minutes of churn, 61k connection cycles, and every emitter I'm watching "
      "holds exactly one listener the whole time. No accumulation on wss, the "
      "broadcast bus, or process. If we had a classic listener leak on a shared "
      "emitter, these counts would be in the tens of thousands by now."),
    T("user",
      "Hm. Before you write it off — wouldn't Node itself have complained? Check "
      "whether we've ever logged MaxListenersExceededWarning anywhere, prod or "
      "local. If Node never warned, that supports dropping this theory."),
    T("tool",
      "$ grep -rn \"MaxListenersExceeded\" logs/ /var/log/ws-gateway/ 2>/dev/null | head\n"
      "(no matches)\n"
      "$ grep -rn \"MaxListenersExceeded\\|possible EventEmitter memory leak\" prod-logs-export/*.jsonl | wc -l\n"
      "0\n"
      "$ node -e \"process.on('warning', w=>console.log('WARN',w.name)); require('./src/server.js')\" &\n"
      "$ node tools/loadtest.js --clients 200 --churn --duration 120\n"
      "loadtest done: 200 clients, 9,881 cycles, 0 errors\n"
      "(no warnings emitted)",
      tool_name="bash"),
    T("assistant",
      "Zero MaxListenersExceededWarning in local runs and in the full production log "
      "export, and the emitter counts stayed flat through 61k cycles. Every "
      "measurable signal says listener registration is balanced. I think this is a "
      "dead end — let's park the listener theory and spend our time on hypothesis B. "
      "The +288k retained strings in the heap diff smell much more like message "
      "payloads pinned in a cache, and cache.js is sitting right there unexamined."),
    T("user",
      "Fine, park it. The string growth was the biggest slice of the diff anyway. Go "
      "hunt for caches — any Map or Set in the codebase that only ever grows."),

    # ------------------------------------------------------------------
    # Segment 2: hypothesis B — unbounded message cache (turns 20-31)
    # ------------------------------------------------------------------
    T("tool",
      "$ grep -rn \"new Map\\|new Set\\|= {}\" src/ | grep -v test\n"
      "src/server.js:12:const registry = new Map();        // connId -> Connection\n"
      "src/cache.js:6:const messageCache = new Map();      // msgId -> {payload, ts, senderId}\n"
      "src/cache.js:7:const pendingAcks = new Map();       // msgId -> timeout handle\n"
      "src/router.js:9:const topicSubs = new Map();        // topic -> Set(connId)\n"
      "src/metrics.js:4:const counters = {};\n"
      "$ grep -n \"delete\\|clear()\" src/cache.js\n"
      "src/cache.js:31:    pendingAcks.delete(msgId);\n"
      "(no other matches)",
      tool_name="grep"),
    T("assistant",
      "There it is: cache.js keeps messageCache, a Map from msgId to the full "
      "payload, and the only delete in the whole file is for pendingAcks. Nothing "
      "ever removes entries from messageCache — every message the gateway has ever "
      "relayed since boot is still in memory. That lines up with the +288k strings. "
      "Let me read the file to understand what the cache is actually for before "
      "changing it."),
    T("tool",
      "src/cache.js (lines 6-40):\n"
      "  const messageCache = new Map(); // msgId -> {payload, ts, senderId}\n"
      "  const pendingAcks = new Map();\n"
      "\n"
      "  function remember(msg) {\n"
      "    messageCache.set(msg.id, { payload: msg.raw, ts: Date.now(), senderId: msg.from });\n"
      "  }\n"
      "\n"
      "  // Redelivery: if a client reconnects within its session window and asks\n"
      "  // for a msgId it missed, serve it from messageCache.\n"
      "  function redeliver(msgId) {\n"
      "    return messageCache.get(msgId) ?? null;\n"
      "  }\n"
      "\n"
      "  function ack(msgId) {\n"
      "    clearTimeout(pendingAcks.get(msgId));\n"
      "    pendingAcks.delete(msgId);\n"
      "    // NOTE: keep message around \"for a while\" for late redelivery\n"
      "  }",
      tool_name="read_file"),
    T("assistant",
      "Confirmed unbounded. The comment says keep messages 'for a while' but nobody "
      "implemented the eviction, so 'a while' means forever. The redelivery window "
      "only needs recent messages, so the fix is straightforward: bound "
      "messageCache with an LRU capped at 50,000 entries plus a 5-minute TTL sweep, "
      "matching the documented session window. Semantics preserved — any redelivery "
      "request older than the window already gets a miss-and-refetch path."),
    T("user",
      "Do it, but keep it low-risk: no new dependencies, implement the LRU inline, "
      "and put the cap and TTL behind env vars so ops can tune without a deploy. "
      "Default cap 50k like you said."),
    T("assistant",
      "Done. Changes to src/cache.js:\n"
      "- messageCache is now an LRU: on set, if size > CACHE_MAX (env "
      "WS_CACHE_MAX, default 50000), evict oldest insertion via the Map's iteration "
      "order.\n"
      "- A 30-second sweep drops entries older than WS_CACHE_TTL_MS (default "
      "300000).\n"
      "- ack() unchanged; redeliver() unchanged — misses were already handled.\n"
      "Running the existing unit tests plus two new ones for eviction."),
    T("tool",
      "$ npm test\n"
      "> ws-gateway@2.4.1 test\n"
      "> node --test test/\n"
      "✔ connection lifecycle registers and cleans up (12ms)\n"
      "✔ router fanout delivers to topic subscribers (9ms)\n"
      "✔ cache remembers and redelivers within window (3ms)\n"
      "✔ cache evicts beyond CACHE_MAX (new) (5ms)\n"
      "✔ cache TTL sweep drops stale entries (new) (31ms)\n"
      "tests 5, pass 5, fail 0",
      tool_name="bash"),
    T("assistant",
      "Tests green. Now the real question: does the churn load test show a flat "
      "memory profile with eviction in place? Re-running the same 500-client churn "
      "as before so the slopes are directly comparable."),
    T("tool",
      "$ node src/server.js & node tools/loadtest.js --clients 500 --churn --duration 300\n"
      "t=0s    rss=97.1 MB  heapUsed=41.8 MB\n"
      "t=60s   rss=124.3 MB heapUsed=58.7 MB\n"
      "t=120s  rss=150.9 MB heapUsed=75.2 MB\n"
      "t=180s  rss=177.4 MB heapUsed=91.9 MB\n"
      "t=240s  rss=203.8 MB heapUsed=108.4 MB\n"
      "t=300s  rss=230.5 MB heapUsed=125.0 MB\n"
      "cache stats: size=50000 (capped), evictions=41,203, ttl-swept=8,914",
      tool_name="bash"),
    T("assistant",
      "Mixed result. The eviction is working — cache pinned at 50k entries, 41k "
      "evictions — and the leak slope dropped from ~65 MB/min to ~27 MB/min. So the "
      "cache was real and is now fixed. But 27 MB/min of churn-correlated growth "
      "remains, and per your rule we need a 10-minute soak before judging anything "
      "anyway. Running the long soak now; if it plateaus we're done, if it climbs "
      "linearly something else is still leaking."),
    T("tool",
      "$ node tools/soak.js --clients 500 --churn --duration 720\n"
      "t=1m   rss=123.9 MB\n"
      "t=3m   rss=176.2 MB\n"
      "t=5m   rss=229.8 MB\n"
      "t=7m   rss=282.1 MB\n"
      "t=9m   rss=335.6 MB\n"
      "t=11m  rss=388.0 MB\n"
      "t=12m  rss=414.7 MB\n"
      "soak verdict: LINEAR GROWTH ~26.5 MB/min after cache fix",
      tool_name="bash"),
    T("user",
      "So the cache was only part of the story — steady 26 MB/min after twelve "
      "minutes is still a hard leak, just a slower one. Keep the LRU change, it's "
      "correct regardless. What's actually left holding memory?"),

    # ------------------------------------------------------------------
    # Segment 3: return to hypothesis A with new evidence (turns 32-43)
    # ------------------------------------------------------------------
    T("assistant",
      "Let me diff fresh heap snapshots now that the cache noise is gone — with 91 MB "
      "of string growth eliminated, whatever remains should stand out. Actually, "
      "hold on. The retainer summary from that soak still shows thousands of "
      "WebSocket and Timeout objects, the same 1:1 pair from our very first diff. "
      "Wait — look at this retainer path, we were too quick to drop the listener "
      "idea. Timeouts retaining sockets is exactly what a leaked per-socket handler "
      "plus a live timer would look like, and back in the listener investigation we "
      "only ever counted listeners on the *shared* emitters — wss, bus, process — "
      "never on the per-socket emitters themselves. Pulling the retainer paths now."),
    T("tool",
      "$ node tools/snapshot.js --port 9229 --out post-lru-a.heapsnapshot && sleep 300 \\\n"
      "    && node tools/snapshot.js --port 9229 --out post-lru-b.heapsnapshot\n"
      "$ node tools/heapdiff.js post-lru-a.heapsnapshot post-lru-b.heapsnapshot --retainers WebSocket --top 3\n"
      "WebSocket delta: +14,371 objects (+33.2 MB)\n"
      "dominant retainer path (14,290 of 14,371 instances):\n"
      "  (GC roots) -> Timers list\n"
      "    -> Timeout [repeating, 5000ms]\n"
      "    -> _onTimeout: closure tick() in startHeartbeat (src/helpers/heartbeat.js:14)\n"
      "    -> context: socket (WebSocket)\n"
      "    -> socket._events.pong: [Array of 61 closures onPong (heartbeat.js:19)]\n"
      "secondary path (81 instances): loadtest teardown race, ignorable",
      tool_name="bash"),
    T("assistant",
      "There's the smoking gun, and it vindicates re-opening the listener theory. "
      "Two compounding bugs in the heartbeat helper:\n"
      "1. Each closed socket carries an array of ~61 'pong' listeners — a new one "
      "was added on every 5-second tick. Listeners *were* leaking, but on the "
      "per-socket emitters, which is why our earlier instrumentation of wss/bus/"
      "process showed rock-solid 1s. We measured the wrong emitters.\n"
      "2. The heartbeat's repeating Timeout is never cleared on close, so the timer "
      "list keeps the tick closure alive, which keeps the dead socket — and its 61 "
      "listeners, and their captured buffers — reachable forever.\n"
      "Reading heartbeat.js to confirm before patching."),
    T("tool",
      "src/helpers/heartbeat.js (full file, 47 lines):\n"
      "  const HEARTBEAT_MS = 5000;\n"
      "\n"
      "  function startHeartbeat(socket) {\n"
      "    socket.setMaxListeners(0); // sockets are chatty, silence warnings\n"
      "    const timer = setInterval(function tick() {\n"
      "      let alive = false;\n"
      "      const onPong = () => { alive = true; };\n"
      "      socket.on('pong', onPong);          // BUG: added every tick, never removed\n"
      "      socket.ping();\n"
      "      setTimeout(() => {\n"
      "        if (!alive && socket.readyState === 1) socket.terminate();\n"
      "      }, 2500);\n"
      "    }, HEARTBEAT_MS);\n"
      "    // BUG: no clearInterval anywhere — timer outlives the socket\n"
      "  }\n"
      "\n"
      "  module.exports = { startHeartbeat };",
      tool_name="read_file"),
    T("assistant",
      "Full root cause confirmed, including why every earlier signal misled us:\n"
      "- socket.setMaxListeners(0) on line 2 disabled the exact warning we grepped "
      "for — Node stayed silent about 61 stacked 'pong' listeners by design.\n"
      "- The listener pile-up is per-socket, invisible to shared-emitter counts.\n"
      "- The uncleared setInterval is the actual GC anchor: even after 'close', the "
      "timers list roots tick(), tick() closes over socket, and the socket drags "
      "everything else along. ~14k churned sockets per 5 minutes matches the "
      "Timeout delta from the very first heap diff — the clue was there on day one."),
    T("user",
      "So the flat listener counts and the missing Node warning were both artifacts "
      "of how the code was written, not evidence of health. Good lesson. Fix it "
      "properly — one pong listener for the socket's lifetime, and make absolutely "
      "sure that interval dies with the connection."),
    T("assistant",
      "Patch for src/helpers/heartbeat.js:\n"
      "- Register a single persistent 'pong' listener once, outside the interval; "
      "tick() only flips the alive flag check.\n"
      "- Keep the interval handle and add socket.on('close', ...) that runs "
      "clearInterval(timer), clears the pending probe timeout, and calls "
      "socket.removeListener('pong', onPong).\n"
      "- Drop the setMaxListeners(0) hack — with one listener it's unnecessary, and "
      "we want Node's warning back as a tripwire.\n"
      "Applying and showing the diff."),
    T("tool",
      "$ git diff --stat && git diff src/helpers/heartbeat.js | head -30\n"
      " src/helpers/heartbeat.js | 29 ++++++++++++++++-----------\n"
      "-  socket.setMaxListeners(0); // sockets are chatty, silence warnings\n"
      "-  const timer = setInterval(function tick() {\n"
      "-    let alive = false;\n"
      "-    const onPong = () => { alive = true; };\n"
      "-    socket.on('pong', onPong);\n"
      "+  let alive = true;\n"
      "+  const onPong = () => { alive = true; };\n"
      "+  socket.on('pong', onPong);\n"
      "+  const timer = setInterval(function tick() {\n"
      "+    if (!alive && socket.readyState === 1) return socket.terminate();\n"
      "+    alive = false;\n"
      "     socket.ping();\n"
      "-    setTimeout(() => {\n"
      "-      if (!alive && socket.readyState === 1) socket.terminate();\n"
      "-    }, 2500);\n"
      "   }, HEARTBEAT_MS);\n"
      "+  socket.on('close', () => {\n"
      "+    clearInterval(timer);\n"
      "+    socket.removeListener('pong', onPong);\n"
      "+  });",
      tool_name="bash"),
    T("assistant",
      "The diff also simplifies the probe: instead of a per-tick timeout race, each "
      "tick terminates if the previous ping went unanswered — same 5-10 s detection "
      "window, one less timer per tick. Running the unit suite, then an "
      "instrumented churn run that logs per-socket listener counts, which is the "
      "measurement we should have taken the first time around."),
    T("tool",
      "$ npm test\n"
      "✔ connection lifecycle registers and cleans up (11ms)\n"
      "✔ router fanout delivers to topic subscribers (8ms)\n"
      "✔ cache remembers and redelivers within window (3ms)\n"
      "✔ cache evicts beyond CACHE_MAX (4ms)\n"
      "✔ cache TTL sweep drops stale entries (29ms)\n"
      "✔ heartbeat terminates unresponsive socket (new) (5112ms)\n"
      "✔ heartbeat clears interval on close (new) (18ms)\n"
      "tests 7, pass 7, fail 0",
      tool_name="bash"),
    T("assistant",
      "Suite green including the two new heartbeat tests. Now the targeted check: "
      "run churn with per-socket instrumentation sampling listenerCount('pong') on "
      "live sockets and counting active intervals, to prove both bugs are gone at "
      "the mechanism level before we bother with the memory-level soak."),
    T("tool",
      "$ node src/server.js --debug-socket-listeners & node tools/loadtest.js --clients 500 --churn --duration 300\n"
      "t=60s  live-sockets=500 pong-listeners{min:1,max:1,mean:1.0} active-intervals=500\n"
      "t=180s live-sockets=500 pong-listeners{min:1,max:1,mean:1.0} active-intervals=500\n"
      "t=300s live-sockets=500 pong-listeners{min:1,max:1,mean:1.0} active-intervals=500\n"
      "post-run (all clients disconnected, after GC): active-intervals=0\n"
      "heap check: WebSocket instances after gc(): 3 (server internals), was ~14,000",
      tool_name="bash"),

    # ------------------------------------------------------------------
    # Segment 4: verification and regression test (turns 44-49)
    # ------------------------------------------------------------------
    T("user",
      "Exactly one pong listener per socket, zero intervals after disconnect, and "
      "WebSocket instances back to single digits — that's the mechanism fixed. Now "
      "hold it to the bar we agreed on: run the full soak, ten minutes minimum, "
      "before anyone says the word fixed. Give it fifteen to be safe."),
    T("tool",
      "$ node tools/soak.js --clients 500 --churn --duration 900\n"
      "t=1m   rss=112.4 MB heapUsed=48.1 MB\n"
      "t=3m   rss=118.9 MB heapUsed=51.3 MB\n"
      "t=5m   rss=119.6 MB heapUsed=50.8 MB\n"
      "t=7m   rss=120.2 MB heapUsed=51.6 MB\n"
      "t=9m   rss=119.8 MB heapUsed=50.9 MB\n"
      "t=11m  rss=120.5 MB heapUsed=51.4 MB\n"
      "t=13m  rss=120.1 MB heapUsed=51.0 MB\n"
      "t=15m  rss=120.7 MB heapUsed=51.5 MB\n"
      "soak verdict: FLAT (slope 0.02 MB/min after warm-up, within noise)\n"
      "cycles=91,388 errors=0",
      tool_name="bash"),
    T("assistant",
      "Fifteen minutes, 91k connection cycles, RSS flat at ~120 MB after warm-up — "
      "slope is 0.02 MB/min, which is measurement noise. Compare with 65 MB/min "
      "originally and 26 MB/min after the cache-only fix. To keep this from "
      "regressing, I'm adding a leak-guard test to CI: churn 2,000 connections "
      "through a server instance, force GC, and assert that heapUsed returns to "
      "within 10% of baseline and that no Timeout or WebSocket instances survive."),
    T("tool",
      "$ node --test --expose-gc test/leak-guard.test.js\n"
      "✔ leak guard: heapUsed returns to baseline after 2000-conn churn (8,244ms)\n"
      "    baseline=38.2 MB  post-churn+gc=39.1 MB  delta=+2.4% (limit 10%)\n"
      "✔ leak guard: no stray timers or sockets after churn (8,301ms)\n"
      "    active timers: 2 (server internals)  WebSocket instances: 3\n"
      "tests 2, pass 2, fail 0\n"
      "$ git add -A && git status --short\n"
      "M  src/cache.js\n"
      "M  src/helpers/heartbeat.js\n"
      "A  test/leak-guard.test.js\n"
      "M  test/cache.test.js",
      tool_name="bash"),
    T("user",
      "Soak flat, leak guard in CI — that closes it. Write me the short summary for "
      "the incident doc and the PR description, including why the first pass over "
      "listeners came up empty."),
    T("assistant",
      "Summary for the incident doc:\n"
      "- Symptom: ws-gateway RSS grew ~40 MB/h in prod, OOM every ~2 days.\n"
      "- Root causes (two, compounding): (1) heartbeat.js added a new per-socket "
      "'pong' listener every 5 s and never cleared its setInterval, so every closed "
      "socket stayed GC-rooted via the timers list with dozens of stacked "
      "listeners; (2) messageCache in cache.js had no eviction, pinning every "
      "relayed payload forever.\n"
      "- Why the listener leak was missed initially: instrumentation counted "
      "listeners on shared emitters only, and setMaxListeners(0) had silenced "
      "Node's built-in warning — the leak lived on per-socket emitters. The heap "
      "retainer diff (Timeout -> tick closure -> socket) exposed it.\n"
      "- Fixes: single lifetime pong listener + clearInterval on close; LRU (50k) "
      "with 5-min TTL on messageCache, both env-tunable.\n"
      "- Verification: 15-min, 91k-cycle soak flat at 0.02 MB/min; leak-guard "
      "regression test added to CI. No production pods were restarted during the "
      "investigation, so live heaps remain available for post-hoc comparison."),
]

CASE = Case(
    case_id="c2",
    title="Memory leak hunt in a Node.js websocket gateway (abandoned-then-resumed hypothesis)",
    turns=TURNS,
    segments=[
        Segment(name="Reproduce the leak", start=0, end=9),
        Segment(name="Hypothesis A: event-listener leak (abandoned)", start=10, end=19),
        Segment(name="Hypothesis B: unbounded message cache (partial fix)", start=20, end=31),
        Segment(name="Return to hypothesis A with heap-diff evidence (real fix)", start=32, end=43),
        Segment(name="Verification and regression test", start=44, end=49),
    ],
    constraints=[
        GoldConstraint(turn=0, text="do not restart the production pods while we debug"),
        GoldConstraint(turn=8, text="always run the soak test for at least 10 minutes before calling it fixed"),
    ],
    backtracks=[
        Backtrack(
            from_segment=3,
            to_segment=1,
            note="returned to the listener hypothesis with heap-diff evidence",
        ),
    ],
)
