(() => {
  const $ = (id) => document.getElementById(id);
  let sock = null;
  let lang = "en";
  let hearing = false;
  let captions = Lekha.cacheGet("captions", []);
  let notes = Lekha.cacheGet("notes", []);
  let glossary = Lekha.cacheGet("glossary", []);
  let lastBytes = 0;
  let windowBytes = 0;
  let joined = false;

  const names = { en: "English", hi: "हिन्दी", ta: "தமிழ்", bn: "বাংলা", es: "Español" };

  document.querySelectorAll(".tab").forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("on"));
      t.classList.add("on");
      const id = t.dataset.tab;
      $("panelLive").hidden = id !== "live";
      $("panelNotes").hidden = id !== "notes";
      $("panelGloss").hidden = id !== "gloss";
    };
  });

  $("btnBig").onclick = () => document.body.classList.toggle("large");
  $("btnHc").onclick = () => {
    document.body.classList.toggle("hi-contrast");
    $("contrast").checked = document.body.classList.contains("hi-contrast");
  };

  $("join").onclick = () => {
    lang = $("lang").value;
    hearing = $("hearing").checked;
    if ($("contrast").checked) document.body.classList.add("hi-contrast");
    if (hearing) document.body.classList.add("large");
    $("langLive").value = lang;
    $("gate").hidden = true;
    $("app").hidden = false;
    joined = true;
    connect();
    renderAll();
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  };

  $("langLive").onchange = () => {
    lang = $("langLive").value;
    sock && sock.send({ type: "set_lang", lang });
    renderCaps();
    paintCinema(captions[captions.length - 1]);
  };

  window.addEventListener("online", () => document.body.classList.remove("offline"));
  window.addEventListener("offline", () => document.body.classList.add("offline"));

  function connect() {
    sock = Lekha.connect(
      "student",
      (msg) => onMsg(msg),
      (st) => {
        $("conn").textContent = st === "open" ? "LAN · live" : "LAN · reconnecting";
        $("conn").className = "pill " + (st === "open" ? "ok" : "live");
        document.body.classList.toggle("offline", st !== "open");
      }
    );
  }

  function onMsg(msg) {
    if (msg.type === "hello") {
      sock.send({
        type: "join",
        name: $("name").value.trim() || "Student",
        lang,
        hearing,
        a11y: hearing,
      });
      hydrate(msg.state);
      return;
    }
    if (msg.type === "reset") {
      captions = [];
      notes = [];
      glossary = [];
      persist();
      renderAll();
      $("cinema").innerHTML = "<small>Live caption</small>Waiting for the lecture to start…";
      return;
    }
    if (msg.type === "partial") {
      paintCinema(msg.caption, true);
      return;
    }
    if (msg.type === "caption") {
      captions.push(msg.caption);
      if (captions.length > 200) captions = captions.slice(-200);
      persist();
      appendCap(msg.caption);
      paintCinema(msg.caption);
      buzz(12);
      meter(msg.bytes);
    }
    if (msg.type === "note") {
      notes.push(msg.note);
      persist();
      renderNotes();
    }
    if (msg.type === "glossary") {
      glossary.push(msg.entry);
      persist();
      renderGloss();
    }
    if (msg.type === "alert") {
      flash(msg.alert);
      buzz(40);
    }
    if (msg.state && msg.type === "roster") {
      /* ignore */
    }
  }

  function hydrate(state) {
    if (!state) return;
    captions = state.captions || captions;
    notes = state.notes || notes;
    glossary = state.glossary || glossary;
    persist();
    renderAll();
    if (captions.length) paintCinema(captions[captions.length - 1]);
  }

  function persist() {
    Lekha.cacheSet("captions", captions);
    Lekha.cacheSet("notes", notes);
    Lekha.cacheSet("glossary", glossary);
  }

  function textOf(c) {
    return c[lang] || c.en || "";
  }

  function appendCap(c) {
    const el = document.createElement("div");
    el.className = "cap" + (c.spk === "Student" ? " student" : "");
    el.innerHTML = `<div class="who">${c.spk}</div><div class="tx">${textOf(c)}</div>`;
    $("caps").appendChild(el);
    el.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function renderCaps() {
    $("caps").innerHTML = "";
    captions.forEach(appendCap);
  }

  function renderNotes() {
    $("panelNotes").innerHTML = notes.length
      ? notes
          .map(
            (n) =>
              `<article class="note-card"><h4>${n.title}</h4><ul>${(n.bullets || [])
                .map((b) => `<li>${b}</li>`)
                .join("")}</ul><p class="simple">${n.simple || ""}</p></article>`
          )
          .join("")
      : '<p class="empty">Notes will land here about once a minute — simplified, not a transcript dump.</p>';
  }

  function renderGloss() {
    $("gloss").innerHTML = glossary.length
      ? glossary
          .map((g) => `<article><dt>${g.term}</dt><dd>${g.def}</dd></article>`)
          .join("")
      : '<p class="empty">Key terms get bolded into a running glossary as the lecture goes.</p>';
  }

  function renderAll() {
    renderCaps();
    renderNotes();
    renderGloss();
  }

  function paintCinema(c, partial) {
    if (!c) return;
    const tag = partial ? "Listening…" : `${c.spk} · ${names[lang] || lang}`;
    $("cinema").innerHTML = `<small>${tag}</small>${textOf(c)}`;
    $("cinema").style.opacity = partial ? "0.75" : "1";
  }

  function flash(alert) {
    const t = $("toast");
    const icon = alert.kind === "bell" ? "🔔" : alert.kind === "laughter" ? "😄" : "⚡";
    t.textContent = `${icon}  ${alert.label}`;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 2800);
  }

  function buzz(ms) {
    if (!hearing) return;
    try {
      navigator.vibrate && navigator.vibrate(ms);
    } catch {}
  }

  function meter(b) {
    if (!b) return;
    windowBytes += b;
  }
  setInterval(() => {
    $("rate").textContent = windowBytes + " B/s";
    windowBytes = 0;
  }, 1000);

  // Returning visitor: skip gate if we already have a name cached? Keep gate for demo control.
})();
