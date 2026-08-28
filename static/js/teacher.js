(() => {
  const vadEl = document.getElementById("vad");
  for (let i = 0; i < 28; i++) {
    const bar = document.createElement("i");
    vadEl.appendChild(bar);
  }
  const bars = [...vadEl.querySelectorAll("i")];

  const $ = (id) => document.getElementById(id);
  const logEl = $("log");
  let bytesSent = 0;
  let packets = 0;
  let startedAt = null;
  let speaking = false;
  let rec = null;
  let liveOn = false;
  let vadTimer = null;
  let requestedLangs = [];
  let micStream = null;
  let pendingInterim = "";
  let flushTimer = null;
  let lastSent = "";

  function setNode(id, on, label) {
    const n = document.getElementById(id);
    n.classList.toggle("active", on);
    n.querySelector(".st").textContent = label;
  }

  function tickVAD(active) {
    speaking = active;
    vadEl.classList.toggle("speaking", active);
    bars.forEach((b, i) => {
      const wave = active
        ? 12 + Math.abs(Math.sin(Date.now() / 120 + i * 0.4)) * 88 * (0.4 + Math.random() * 0.6)
        : 8 + Math.random() * 6;
      b.style.height = wave + "%";
      b.style.opacity = active ? 0.35 + wave / 140 : 0.2;
    });
  }
  setInterval(() => tickVAD(speaking), 80);

  function addLog(caption, size) {
    const row = document.createElement("div");
    row.className = "pk";
    const pkt = {
      t: Math.round((caption.t || Date.now() / 1000) % 100000),
      spk: caption.spk,
      text: (caption.en || "").slice(0, 48),
    };
    row.innerHTML = `<b>${size || "?"}B</b> ${JSON.stringify(pkt)}`;
    logEl.prepend(row);
  }

  function renderRoster(state) {
    requestedLangs = state.requestedLangs || [];
    const box = $("roster");
    if (!state.students.length) {
      box.innerHTML =
        '<p class="empty">Open /student on a phone or a second window. Subscribe-based MT lights up when they pick a language.</p>';
      return;
    }
    box.innerHTML = state.students
      .map((s) => {
        const init = (s.name || "?").slice(0, 1).toUpperCase();
        const qos = s.hearing ? '<span class="qos">QoS 2</span>' : "";
        return `<div class="stu"><div class="ava">${init}</div><div class="nm">${s.name}<small>${s.lang.toUpperCase()}${s.hearing ? " · hearing-impaired" : ""}</small></div>${qos}</div>`;
      })
      .join("");
  }

  function renderNote(note) {
    $("paper").innerHTML = `<h4>${note.title}</h4><ul>${(note.bullets || [])
      .map((b) => `<li>${b}</li>`)
      .join("")}</ul><div class="simple">${note.simple || ""}</div>`;
  }

  function renderMT(caption, langs) {
    langs = langs || [];
    if (!caption) return;
    const pick = langs.find((l) => l !== "en") || langs[0] || "hi";
    const names = { en: "ENGLISH", hi: "HINDI · हिन्दी", ta: "TAMIL · தமிழ்", bn: "BENGALI · বাংলা", es: "SPANISH" };
    if (!langs.length) {
      $("mtLang").textContent = "NO SUBSCRIBERS YET";
      $("mtText").innerHTML = '<span class="empty">Translation is skipped until a student requests a language.</span>';
      setNode("nC", false, "skipped");
      return;
    }
    $("mtLang").textContent = `SUBSCRIBED · ${langs.map((l) => l.toUpperCase()).join(" · ")}`;
    $("mtText").textContent = caption[pick] || caption.en;
    setNode("nC", true, langs.filter((l) => l !== "en").join(",") || "en");
  }

  function applyStats(msg, state) {
    bytesSent = msg.bytesSent ?? state?.stats?.bytesSent ?? bytesSent;
    packets = msg.packets ?? state?.stats?.packets ?? packets;
    startedAt = state?.stats?.startedAt || startedAt;
    $("bytes").textContent = Lekha.fmtBytes(bytesSent);
    $("pkts").textContent = String(packets);
    const elapsed = startedAt ? Math.max(0, Date.now() / 1000 - startedAt) : 0;
    const audio = Math.round(elapsed * 1600);
    $("audioWould").textContent = Lekha.fmtBytes(audio);
    const saved = Math.max(0, audio - bytesSent);
    $("saved").textContent = audio ? Lekha.fmtBytes(saved) : "—";
    const ratio = audio ? Math.min(100, (bytesSent / audio) * 100) : 2;
    $("bwFill").style.width = Math.max(2, ratio) + "%";
  }

  function setMode(mode) {
    const pill = $("modePill");
    if (mode === "demo" || mode === "live") {
      pill.textContent = mode === "demo" ? "DEMO LECTURE" : "LIVE MIC";
      pill.className = "pill live";
      setNode("nMic", true, "hot");
      setNode("nVad", true, "gating");
      setNode("nAsr", true, mode === "demo" ? "whisper.cpp (sim)" : "web-speech");
      setNode("nA", true, "streaming");
      speaking = true;
    } else {
      pill.textContent = "IDLE";
      pill.className = "pill";
      ["nMic", "nVad", "nAsr", "nA", "nB", "nC"].forEach((id) => setNode(id, false, "idle"));
      speaking = false;
    }
  }

  const sock = Lekha.connect(
    "teacher",
    (msg) => {
      if (msg.type === "hello" || msg.type === "roster" || msg.type === "mode" || msg.type === "reset" || msg.type === "ended") {
        const st = msg.state;
        if (st) {
          renderRoster(st);
          if (st.captions?.length) renderMT(st.captions[st.captions.length - 1], st.requestedLangs || []);
          applyStats(msg, st);
          if (st.notes?.length) renderNote(st.notes[st.notes.length - 1]);
          if (st.captions?.length) {
            const last = st.captions[st.captions.length - 1];
            paintCaption(last);
            renderMT(last, st.requestedLangs || []);
          }
          setMode(st.mode);
        }
      }
      if (msg.type === "caption") {
        paintCaption(msg.caption);
        addLog(msg.caption, msg.bytes);
        renderMT(msg.caption, requestedLangs);
        applyStats(msg);
        speaking = true;
        clearTimeout(vadTimer);
        vadTimer = setTimeout(() => {
          if (!liveOn) speaking = $("modePill").textContent !== "IDLE";
        }, 1400);
      }
      if (msg.type === "note") {
        renderNote(msg.note);
        setNode("nB", true, "wrote");
        applyStats(msg);
      }
      if (msg.type === "glossary") applyStats(msg);
      if (msg.type === "alert") {
        $("alertMini").textContent = "ALERT · " + msg.alert.label;
        applyStats(msg);
      }
      if (msg.type === "ended") {
        setMode("idle");
        speaking = false;
      }
      if (msg.type === "reset") {
        logEl.innerHTML = "";
        $("asrLine").innerHTML = '<span class="partial">Waiting for speech…</span>';
        $("paper").innerHTML = '<p class="empty">Notes appear every ~60–90s of speech (compressed in the demo).</p>';
        $("mtText").innerHTML = '<span class="empty">Translation runs only for languages a connected student asked for.</span>';
        $("alertMini").textContent = "";
        bytesSent = 0;
        packets = 0;
        startedAt = null;
        applyStats({ bytesSent: 0, packets: 0 });
        setMode("idle");
      }
    },
    (st) => {
      $("lanPill").textContent = st === "open" ? "LAN · edge online" : "LAN · reconnecting";
    }
  );

  function paintCaption(c) {
    const line = $("asrLine");
    line.className = "asr-line" + (c.spk === "Student" ? " student" : "");
    line.innerHTML = `<span class="spk">${c.spk}</span>${c.en}`;
  }

  $("btnDemo").onclick = () => {
    stopMic();
    sock.send({ type: "start_demo" });
  };
  $("btnStop").onclick = () => {
    stopMic();
    sock.send({ type: "stop" });
  };
  $("btnLive").onclick = () => toggleMic();

  function toggleMic() {
    if (liveOn) {
      stopMic();
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      alert("Live mic needs the Web Speech API (Chrome/Edge). Use the demo lecture on this browser.");
      return;
    }
    sock.send({ type: "start_live" });
    rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-IN";
    rec.onresult = (ev) => {
      speaking = true;
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript.trim();
        if (ev.results[i].isFinal) {
          sock.send({ type: "live_caption", spk: "Teacher", text: t });
        } else {
          interim += t + " ";
        }
      }
      if (interim) {
        $("asrLine").innerHTML = `<span class="spk">Teacher</span><span class="partial">${interim}</span>`;
      }
    };
    rec.onend = () => {
      if (liveOn) rec.start();
    };
    rec.start();
    liveOn = true;
    $("btnLive").textContent = "Stop mic";
    setMode("live");
  }

  function stopMic() {
    liveOn = false;
    if (rec) {
      try {
        rec.stop();
      } catch {}
      rec = null;
    }
    $("btnLive").textContent = "Live mic";
  }
})();
