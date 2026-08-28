const Lekha = {
  wsUrl(role) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}/ws/${role}`;
  },
  connect(role, onMsg, onStatus) {
    let ws;
    let tries = 0;
    const open = () => {
      ws = new WebSocket(Lekha.wsUrl(role));
      ws.onopen = () => {
        tries = 0;
        onStatus && onStatus("open");
      };
      ws.onclose = () => {
        onStatus && onStatus("closed");
        tries += 1;
        setTimeout(open, Math.min(2000 * tries, 8000));
      };
      ws.onerror = () => {};
      ws.onmessage = (ev) => {
        try {
          onMsg(JSON.parse(ev.data));
        } catch (e) {}
      };
    };
    open();
    return {
      send(obj) {
        if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
      },
    };
  },
  fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  },
  cacheGet(key, fallback) {
    try {
      const v = localStorage.getItem("lekha:" + key);
      return v ? JSON.parse(v) : fallback;
    } catch {
      return fallback;
    }
  },
  cacheSet(key, val) {
    try {
      localStorage.setItem("lekha:" + key, JSON.stringify(val));
    } catch {}
  },
};
