"""Built-in single-page dashboard for live demos.

Serves a tiny self-contained HTML page at ``GET /api/v1/demo`` that:

1. Logs in against ``POST /api/v1/auth/token`` using the credentials typed
   into the form (the page never persists them — they live in
   ``sessionStorage`` for the lifetime of the tab).
2. Subscribes to the SSE stream at ``GET /api/v1/alerts/stream``.
3. Renders incoming alerts in a real-time table and refreshes the
   ``GET /api/v1/stats`` summary every 3 seconds.

This is intentionally a zero-build, single-file dashboard for the
committee demo. The mainline frontend stays the responsibility of the
separate Flutter / Chrome-extension clients documented in
``docs/FLUTTER_DEVELOPER_GUIDE.md`` and the post-demo roadmap.

The page contains no inline credentials and no embedded server secrets;
all state is JWT-protected via the existing auth flow. CSP is set to a
tight ``default-src 'self'`` with a single ``'unsafe-inline'`` for the
embedded ``<style>`` and ``<script>`` blocks (no remote resources).
"""

from __future__ import annotations

from flask import Blueprint, Response

demo_bp = Blueprint("demo", __name__, url_prefix="/api/v1")


_DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RT-AI-IDS — Live Demo</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system,
         "Segoe UI", Roboto, sans-serif; background: #0b1020; color: #e6edf3; }
  header { padding: 12px 20px; background: #111a36; border-bottom: 1px solid #233; }
  header h1 { margin: 0; font-size: 18px; letter-spacing: 0.5px; }
  header small { color: #8aa1c1; }
  main { padding: 16px 20px; }
  .login { max-width: 420px; margin: 80px auto; padding: 24px; background: #131c3a;
           border: 1px solid #233; border-radius: 8px; }
  .login h2 { margin: 0 0 16px; }
  .login label { display: block; margin: 12px 0 4px; font-size: 12px; color: #8aa1c1; }
  .login input { width: 100%; padding: 8px 10px; background: #0b1020; color: #e6edf3;
                 border: 1px solid #2a355a; border-radius: 4px; }
  .login button { margin-top: 16px; width: 100%; padding: 10px; background: #2a6df4;
                  color: white; border: 0; border-radius: 4px; cursor: pointer; }
  .login button:disabled { opacity: 0.5; cursor: not-allowed; }
  .err { color: #ff8b8b; margin-top: 10px; min-height: 18px; font-size: 13px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 12px; margin-bottom: 16px; }
  .card { background: #131c3a; border: 1px solid #233; border-radius: 8px; padding: 12px 14px; }
  .card .k { font-size: 12px; color: #8aa1c1; text-transform: uppercase; letter-spacing: 1px; }
  .card .v { font-size: 28px; font-weight: 700; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; background: #131c3a;
          border: 1px solid #233; border-radius: 8px; overflow: hidden; }
  th, td { padding: 8px 10px; border-bottom: 1px solid #1f2a4a; text-align: left; }
  th { background: #182347; color: #aab9d6; font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: 1px; }
  tr.new { animation: pulse 1.2s ease-out 1; }
  @keyframes pulse { 0% { background: #2a6df4; } 100% { background: transparent; } }
  .risk { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;
          letter-spacing: 0.5px; text-transform: uppercase; }
  .risk-critical { background: #b3261e; color: white; }
  .risk-high     { background: #e0561a; color: white; }
  .risk-medium   { background: #c0930a; color: #1a1a1a; }
  .risk-low      { background: #2e7d32; color: white; }
  .risk-info, .risk-benign { background: #2a355a; color: #cdd9f0; }
  .pill { display: inline-block; padding: 2px 6px; background: #0e1730; border: 1px solid #233;
          border-radius: 4px; color: #aab9d6; font-family: ui-monospace, SFMono-Regular, monospace; }
  .conn { font-size: 11px; color: #8aa1c1; }
  .conn.ok { color: #6ee7a7; }
  .conn.err { color: #ff8b8b; }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
</style>
</head>
<body>

<header class="row">
  <div>
    <h1>RT-AI-IDS — Live Demo</h1>
    <small>Real-time intrusion detection · committee demo dashboard</small>
  </div>
  <div id="connStatus" class="conn">disconnected</div>
</header>

<main>
  <section id="login" class="login">
    <h2>Sign in</h2>
    <form id="loginForm">
      <label for="u">Username</label>
      <input id="u" name="username" autocomplete="username" required>
      <label for="p">Password</label>
      <input id="p" name="password" type="password" autocomplete="current-password" required>
      <button id="loginBtn" type="submit">Sign in</button>
      <div id="loginErr" class="err"></div>
    </form>
  </section>

  <section id="dashboard" hidden>
    <div class="stats">
      <div class="card"><div class="k">Total alerts</div><div class="v" id="totalAlerts">0</div></div>
      <div class="card"><div class="k">Critical</div>     <div class="v" id="riskCritical">0</div></div>
      <div class="card"><div class="k">High</div>         <div class="v" id="riskHigh">0</div></div>
      <div class="card"><div class="k">Medium / Low</div> <div class="v" id="riskOther">0</div></div>
    </div>
    <table>
      <thead><tr>
        <th>#</th><th>When</th><th>Risk</th><th>Source IP</th><th>Dest port</th>
        <th>Classification</th><th>Score</th><th>Rationale</th>
      </tr></thead>
      <tbody id="alertRows">
        <tr><td colspan="8" style="text-align:center; color:#8aa1c1; padding:30px;">
          Waiting for alerts… run an attack from the attacker machine.
        </td></tr>
      </tbody>
    </table>
  </section>
</main>

<script>
(function () {
  const TOKEN_KEY = "rt-ai-ids-demo-token";
  const POLL_STATS_MS = 3000;

  const $ = (id) => document.getElementById(id);
  const setConn = (text, cls) => {
    const el = $("connStatus");
    el.textContent = text;
    el.className = "conn " + (cls || "");
  };
  const fmtTime = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleTimeString(); }
    catch (_e) { return String(iso); }
  };
  const escapeHtml = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const knownIds = new Set();

  async function login(u, p) {
    const r = await fetch("/api/v1/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) {
      let msg = "Login failed (" + r.status + ")";
      try { const j = await r.json(); if (j && j.error) msg = j.error; } catch (_e) {}
      throw new Error(msg);
    }
    const j = await r.json();
    return j.access_token;
  }

  async function fetchStats(token) {
    const r = await fetch("/api/v1/stats", { headers: { Authorization: "Bearer " + token } });
    if (!r.ok) return null;
    return r.json();
  }

  function renderStats(stats) {
    if (!stats) return;
    $("totalAlerts").textContent = stats.total_alerts || 0;
    const dist = stats.risk_distribution || {};
    $("riskCritical").textContent = dist.critical || 0;
    $("riskHigh").textContent = dist.high || 0;
    $("riskOther").textContent = (dist.medium || 0) + (dist.low || 0) + (dist.info || 0);
  }

  function appendAlert(a) {
    if (!a || a.id == null) return;
    if (knownIds.has(a.id)) return;
    knownIds.add(a.id);
    const tbody = $("alertRows");
    if (tbody.querySelector("td[colspan]")) tbody.innerHTML = "";
    const tr = document.createElement("tr");
    tr.className = "new";
    const risk = String(a.risk_label || "info").toLowerCase();
    tr.innerHTML =
      "<td>" + escapeHtml(a.id) + "</td>" +
      "<td>" + escapeHtml(fmtTime(a.created_at)) + "</td>" +
      "<td><span class=\\"risk risk-" + escapeHtml(risk) + "\\">" + escapeHtml(risk) + "</span></td>" +
      "<td><span class=\\"pill\\">" + escapeHtml(a.source_ip || "—") + "</span></td>" +
      "<td>" + escapeHtml(a.destination_port == null ? "—" : a.destination_port) + "</td>" +
      "<td>" + escapeHtml(a.classification || "—") + "</td>" +
      "<td>" + escapeHtml(
        a.probability != null ? Number(a.probability).toFixed(2) : "—"
      ) + "</td>" +
      "<td>" + escapeHtml(
        Array.isArray(a.rationale) ? a.rationale.join(", ") : (a.rationale || "")
      ) + "</td>";
    tbody.insertBefore(tr, tbody.firstChild);
    while (tbody.children.length > 200) tbody.removeChild(tbody.lastChild);
  }

  function connectStream(token) {
    setConn("connecting…", "");
    const url = "/api/v1/alerts/stream?access_token=" + encodeURIComponent(token);
    const es = new EventSource(url);
    es.onopen = () => setConn("● live", "ok");
    es.onerror = () => setConn("● disconnected (retrying)", "err");
    es.onmessage = (ev) => {
      try { appendAlert(JSON.parse(ev.data)); }
      catch (e) { /* ignore malformed frames */ }
    };
    return es;
  }

  async function start(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
    $("login").hidden = true;
    $("dashboard").hidden = false;

    const stats = await fetchStats(token);
    renderStats(stats);
    setInterval(async () => {
      try { renderStats(await fetchStats(token)); } catch (_e) {}
    }, POLL_STATS_MS);

    connectStream(token);
  }

  $("loginForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("loginBtn").disabled = true;
    $("loginErr").textContent = "";
    try {
      const u = $("u").value.trim();
      const p = $("p").value;
      const token = await login(u, p);
      await start(token);
    } catch (e) {
      $("loginErr").textContent = e.message || "Login failed";
    } finally {
      $("loginBtn").disabled = false;
    }
  });

  const cached = sessionStorage.getItem(TOKEN_KEY);
  if (cached) {
    fetchStats(cached).then((s) => {
      if (s) start(cached);
    }).catch(() => {});
  }
})();
</script>
</body>
</html>
"""


@demo_bp.get("/demo")
def demo_page() -> Response:
    """Return the single-file demo dashboard."""
    response = Response(_DEMO_HTML, mimetype="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "no-store"
    # Tight CSP — no remote resources, only inline styles/scripts.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
