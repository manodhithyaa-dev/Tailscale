(() => {
  const $ = id => document.getElementById(id);
  let socket = null, buf = "";
  const containerEndpoint = "/api/containers";
  const ANSI = /\x1b\[[0-9;?]*[ -\/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Za-z0-9]/g;
  function state(text, kind = "") { const n = $("connectionState"); n.className = `connection-state ${kind}`; n.lastChild.textContent = ` ${text}`; }
  function append(text) {
    const out = $("terminalOutput"); if (out.querySelector(".terminal-muted")) out.replaceChildren();
    for (const ch of String(text).replace(ANSI, "")) { if (ch === "\b") buf = buf.slice(0, -1); else if (ch !== "\r" && ch !== "\x07") buf += ch; }
    if (buf.length > 200000) buf = buf.slice(-150000);
    out.textContent = buf; out.scrollTop = out.scrollHeight;
  }
  function setConnected(c) { $("terminalInput").disabled = !c; $("terminalForm").querySelector("button").disabled = !c; $("connectTerminal").disabled = c; $("disconnectTerminal").disabled = !c; }
  async function loadContainers() {
    try {
      const data = await api("/containers"), select = $("containerSelect");
      select.replaceChildren(new Option("Choose a running container", ""));
      data.containers.filter(c => c.status === "running").forEach(c => select.add(new Option(`${c.name} · ${c.status}`, c.id)));
      if (select.options.length === 1) toast("No running instances. Create or start one on the EC2 page.", "error");
    } catch (e) { toast("Could not load containers: " + e.message, "error"); }
  }
  function connect() {
    const id = $("containerSelect").value; if (!id) return toast("Select a running container first.", "error");
    const url = new URL(`/api/containers/${encodeURIComponent(id)}/terminal`, location.href); url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    state("Connecting…", "connecting"); buf = ""; $("terminalOutput").replaceChildren();
    socket = new WebSocket(url);
    socket.addEventListener("open", () => { state("Connected", "connected"); $("containerMeta").textContent = $("containerSelect").selectedOptions[0].textContent; setConnected(true); $("terminalInput").focus(); socket.send("\n"); });
    socket.addEventListener("message", ev => { if (typeof ev.data === "string") append(ev.data); });
    socket.addEventListener("error", () => { append("\n[Terminal connection error]\n"); state("Connection error"); setConnected(false); });
    socket.addEventListener("close", () => { if (socket) { state("Disconnected"); setConnected(false); socket = null; } });
  }
  function disconnect() { if (socket) { const s = socket; socket = null; s.close(1000, "User disconnected"); } state("Disconnected"); setConnected(false); }
  document.addEventListener("DOMContentLoaded", async () => {
    try { await nimbusReady; } catch (e) { return; }
    loadContainers();
    $("connectTerminal").addEventListener("click", connect); $("disconnectTerminal").addEventListener("click", disconnect);
    $("clearTerminal").addEventListener("click", () => { buf = ""; $("terminalOutput").replaceChildren(); });
    $("containerSelect").addEventListener("change", e => { $("containerMeta").textContent = e.target.selectedOptions[0]?.textContent || "No container selected"; });
    $("terminalForm").addEventListener("submit", e => { e.preventDefault(); if (!socket || socket.readyState !== WebSocket.OPEN) return; const i = $("terminalInput"); socket.send(i.value + "\n"); i.value = ""; });   // shell echoes the command itself
  });
  window.addEventListener("beforeunload", () => socket?.close(1000, "Page closed"));
})();
