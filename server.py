"""
Lekha — classroom edge device (hackathon prototype)
ASR / MT / summarization are simulated or browser-sourced so this
runs on a laptop without shipping multi-GB models.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
LECTURE = json.loads((ROOT / "demo_lecture.json").read_text(encoding="utf-8"))

LANG_META = {
    "en": {"name": "English", "native": "English"},
    "hi": {"name": "Hindi", "native": "हिन्दी"},
    "ta": {"name": "Tamil", "native": "தமிழ்"},
    "bn": {"name": "Bengali", "native": "বাংলা"},
    "es": {"name": "Spanish", "native": "Español"},
}

# Tiny on-device "MT" for live mic phrases (demo stand-in for NLLB).
HI_LEX = {
    "good": "अच्छा", "morning": "सुप्रभात", "class": "कक्षा", "today": "आज",
    "we": "हम", "study": "पढ़ते हैं", "text": "टेक्स्ट", "is": "है",
    "cheap": "सस्ता", "audio": "ऑडियो", "expensive": "महंगा", "video": "वीडियो",
    "the": "", "a": "", "an": "", "and": "और", "or": "या", "of": "का",
    "to": "को", "in": "में", "on": "पर", "for": "के लिए", "from": "से",
    "network": "नेटवर्क", "bandwidth": "बैंडविड्थ", "lecture": "व्याख्यान",
    "captions": "कैप्शन", "notes": "नोट्स", "phone": "फ़ोन", "student": "छात्र",
    "teacher": "शिक्षक", "internet": "इंटरनेट", "local": "स्थानीय",
    "device": "डिवाइस", "edge": "एज", "speech": "वाणी", "language": "भाषा",
    "translation": "अनुवाद", "please": "कृपया", "thank": "धन्यवाद",
    "yes": "हाँ", "no": "नहीं", "question": "प्रश्न", "answer": "उत्तर",
    "important": "महत्वपूर्ण", "remember": "याद रखें", "because": "क्योंकि",
    "this": "यह", "that": "वह", "not": "नहीं", "need": "ज़रूरत",
    "your": "आपका", "you": "आप", "can": "सकते हैं", "cannot": "नहीं सकते",
    "stream": "स्ट्रीम", "data": "डेटा", "byte": "बाइट", "bytes": "बाइट्स",
}


def naive_hi(text: str) -> str:
    words = re.findall(r"[A-Za-z']+|[\u0900-\u097F]+|[^\s]", text)
    out = []
    for w in words:
        key = w.lower()
        if key in HI_LEX:
            tok = HI_LEX[key]
            if tok:
                out.append(tok)
        else:
            out.append(w)
    joined = " ".join(out)
    joined = re.sub(r"\s+([,.!?।])", r"\1", joined)
    return re.sub(r"\s+", " ", joined).strip() or text


def extractive_note(captions: list[str]) -> dict[str, Any]:
    blob = " ".join(captions[-8:])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", blob) if s.strip()]
    if not sentences:
        sentences = captions[-3:]
    scored = sorted(sentences, key=lambda s: len(s.split()), reverse=True)
    bullets = scored[:3] or sentences[:3]
    simple = " ".join((bullets[0] if bullets else blob).split()[:18])
    if simple and not simple.endswith("."):
        simple += "."
    return {
        "title": "Rolling notes (live pass)",
        "bullets": bullets,
        "simple": simple or "Listening for the next key point.",
    }


def extract_terms(text: str) -> list[str]:
    stop = {
        "The", "This", "That", "Today", "Good", "Exactly", "So", "If", "For",
        "Your", "You", "We", "A", "An", "Job", "Ma'am", "Virginia", "Phones",
    }
    found = []
    for m in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text):
        if m not in stop and m not in found:
            found.append(m)
    acr = re.findall(r"\b[A-Z]{2,}\b", text)
    for a in acr:
        if a not in found:
            found.append(a)
    return found[:4]


class Classroom:
    def __init__(self) -> None:
        self.teacher: WebSocket | None = None
        self.students: dict[str, dict[str, Any]] = {}
        self.captions: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.glossary: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.bytes_sent = 0
        self.packets = 0
        self.started_at: float | None = None
        self.mode = "idle"  # idle | demo | live
        self.demo_task: asyncio.Task | None = None
        self.live_buffer: list[str] = []
        self.last_note_at = 0.0
        self.lock = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        langs = sorted({s["lang"] for s in self.students.values()})
        return {
            "mode": self.mode,
            "title": LECTURE["title"],
            "subject": LECTURE["subject"],
            "teacher": LECTURE["teacher"],
            "students": [
                {
                    "id": sid,
                    "name": s["name"],
                    "lang": s["lang"],
                    "a11y": s["a11y"],
                    "hearing": s["hearing"],
                }
                for sid, s in self.students.items()
            ],
            "requestedLangs": langs,
            "captions": self.captions[-80:],
            "notes": self.notes,
            "glossary": self.glossary,
            "alerts": self.alerts[-12:],
            "stats": {
                "bytesSent": self.bytes_sent,
                "packets": self.packets,
                "students": len(self.students),
                "startedAt": self.started_at,
                "audioWouldHaveBeen": int(
                    max(0, (time.time() - (self.started_at or time.time()))) * 1600
                ),
            },
        }

    async def broadcast(self, payload: dict[str, Any], *, caption_priority: bool = False) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        size = len(raw.encode("utf-8"))
        self.bytes_sent += size
        self.packets += 1
        payload_with_meta = dict(payload)
        payload_with_meta["bytes"] = size
        payload_with_meta["packets"] = self.packets
        payload_with_meta["bytesSent"] = self.bytes_sent
        msg = json.dumps(payload_with_meta, ensure_ascii=False)

        targets: list[WebSocket] = []
        if self.teacher:
            targets.append(self.teacher)
        # Hearing-impaired first (simulated QoS)
        ordered = sorted(
            self.students.values(),
            key=lambda s: (0 if s["hearing"] else 1),
        )
        for s in ordered:
            targets.append(s["ws"])

        dead: list[str] = []
        for ws in targets:
            try:
                await ws.send_text(msg)
            except Exception:
                if ws is self.teacher:
                    self.teacher = None
                else:
                    for sid, st in list(self.students.items()):
                        if st["ws"] is ws:
                            dead.append(sid)
        for sid in dead:
            self.students.pop(sid, None)

    async def emit_caption(self, rec: dict[str, Any]) -> None:
        rec.setdefault("id", uuid.uuid4().hex[:8])
        rec.setdefault("t", time.time())
        rec.setdefault("qos", "high" if rec.get("spk") else "normal")
        self.captions.append(rec)
        await self.broadcast({"type": "caption", "caption": rec}, caption_priority=True)
        # opportunistic glossary from live text
        if rec.get("source") == "live":
            for term in extract_terms(rec.get("en", "")):
                if not any(g["term"].lower() == term.lower() for g in self.glossary):
                    g = {
                        "term": term,
                        "def": "Flagged from live speech — add a definition after class.",
                    }
                    self.glossary.append(g)
                    await self.broadcast({"type": "glossary", "entry": g})

    async def emit_note(self, note: dict[str, Any]) -> None:
        note.setdefault("id", uuid.uuid4().hex[:8])
        note.setdefault("t", time.time())
        self.notes.append(note)
        await self.broadcast({"type": "note", "note": note})

    async def reset(self) -> None:
        if self.demo_task:
            self.demo_task.cancel()
            self.demo_task = None
        self.captions.clear()
        self.notes.clear()
        self.glossary.clear()
        self.alerts.clear()
        self.bytes_sent = 0
        self.packets = 0
        self.started_at = None
        self.mode = "idle"
        self.live_buffer.clear()
        self.last_note_at = 0.0
        await self.broadcast({"type": "reset", "state": self.snapshot()})


room = Classroom()
app = FastAPI(title="Lekha Edge")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/teacher")
async def teacher_page():
    return FileResponse(STATIC / "teacher.html")


@app.get("/student")
async def student_page():
    return FileResponse(STATIC / "student.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(STATIC / "manifest.json")


@app.get("/sw.js")
async def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/api/state")
async def api_state():
    return room.snapshot()


@app.get("/api/export.md")
async def api_export():
    lines = [
        f"# {LECTURE['title']}",
        f"*{LECTURE['subject']} · {LECTURE['teacher']}*",
        "",
        "## Transcript",
        "",
    ]
    for c in room.captions:
        lines.append(f"- **{c.get('spk', 'Teacher')}:** {c.get('en', '')}")
    lines += ["", "## Notes", ""]
    for n in room.notes:
        lines.append(f"### {n.get('title', 'Notes')}")
        for b in n.get("bullets", []):
            lines.append(f"- {b}")
        if n.get("simple"):
            lines.append(f"\n> Simplified: {n['simple']}\n")
    lines += ["", "## Glossary", ""]
    for g in room.glossary:
        lines.append(f"- **{g['term']}** — {g['def']}")
    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")


@app.websocket("/ws/teacher")
async def ws_teacher(ws: WebSocket):
    await ws.accept()
    room.teacher = ws
    await ws.send_text(json.dumps({"type": "hello", "role": "teacher", "state": room.snapshot()}, ensure_ascii=False))
    await room.broadcast({"type": "roster", "state": room.snapshot()})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "start_demo":
                await start_demo()
            elif kind == "start_live":
                await start_live()
            elif kind == "stop":
                await room.reset()
            elif kind == "live_caption":
                await handle_live_caption(msg)
            elif kind == "live_partial":
                await handle_live_partial(msg)
            elif kind == "alert":
                alert = {
                    "id": uuid.uuid4().hex[:8],
                    "t": time.time(),
                    "kind": msg.get("kind", "event"),
                    "label": msg.get("label", "Classroom event"),
                    "en": msg.get("en", "A non-speech event occurred."),
                }
                room.alerts.append(alert)
                await room.broadcast({"type": "alert", "alert": alert}, caption_priority=True)
    except WebSocketDisconnect:
        if room.teacher is ws:
            room.teacher = None


@app.websocket("/ws/student")
async def ws_student(ws: WebSocket):
    await ws.accept()
    sid = uuid.uuid4().hex[:6]
    profile = {
        "ws": ws,
        "id": sid,
        "name": "Student",
        "lang": "en",
        "a11y": False,
        "hearing": False,
    }
    room.students[sid] = profile
    await ws.send_text(
        json.dumps(
            {"type": "hello", "role": "student", "id": sid, "state": room.snapshot()},
            ensure_ascii=False,
        )
    )
    await room.broadcast({"type": "roster", "state": room.snapshot()})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "join":
                profile["name"] = (msg.get("name") or "Student")[:24]
                profile["lang"] = msg.get("lang") if msg.get("lang") in LANG_META else "en"
                profile["a11y"] = bool(msg.get("a11y"))
                profile["hearing"] = bool(msg.get("hearing"))
                await room.broadcast({"type": "roster", "state": room.snapshot()})
            elif msg.get("type") == "set_lang":
                profile["lang"] = msg.get("lang") if msg.get("lang") in LANG_META else "en"
                await room.broadcast({"type": "roster", "state": room.snapshot()})
            elif msg.get("type") == "set_hearing":
                profile["hearing"] = bool(msg.get("hearing"))
                await room.broadcast({"type": "roster", "state": room.snapshot()})
    except WebSocketDisconnect:
        room.students.pop(sid, None)
        await room.broadcast({"type": "roster", "state": room.snapshot()})


async def start_demo() -> None:
    if room.demo_task:
        room.demo_task.cancel()
    room.captions.clear()
    room.notes.clear()
    room.glossary.clear()
    room.alerts.clear()
    room.bytes_sent = 0
    room.packets = 0
    room.live_buffer.clear()
    room.mode = "demo"
    room.started_at = time.time()
    await room.broadcast({"type": "mode", "mode": "demo", "state": room.snapshot()})
    room.demo_task = asyncio.create_task(run_demo())


async def start_live() -> None:
    if room.demo_task:
        room.demo_task.cancel()
        room.demo_task = None
    room.captions.clear()
    room.notes.clear()
    room.glossary.clear()
    room.alerts.clear()
    room.bytes_sent = 0
    room.packets = 0
    room.live_buffer.clear()
    room.last_note_at = time.time()
    room.mode = "live"
    room.started_at = time.time()
    await room.broadcast({"type": "mode", "mode": "live", "state": room.snapshot()})


async def handle_live_partial(msg: dict[str, Any]) -> None:
    if room.mode != "live":
        room.mode = "live"
        room.started_at = room.started_at or time.time()
    text = (msg.get("text") or "").strip()
    if not text:
        return
    rec = {
        "spk": msg.get("spk") or "Teacher",
        "en": text,
        "hi": naive_hi(text),
        "ta": text,
        "bn": text,
        "es": text,
        "source": "live",
        "partial": True,
    }
    await room.broadcast({"type": "partial", "caption": rec}, caption_priority=True)


async def handle_live_caption(msg: dict[str, Any]) -> None:
    if room.mode != "live":
        room.mode = "live"
        room.started_at = room.started_at or time.time()
    text = (msg.get("text") or "").strip()
    if not text:
        return
    spk = msg.get("spk") or "Teacher"
    rec = {
        "spk": spk,
        "en": text,
        "hi": naive_hi(text),
        "ta": text,
        "bn": text,
        "es": text,
        "source": "live",
        "mt": {"hi": "on-device-lexicon", "ta": "passthrough", "bn": "passthrough", "es": "passthrough"},
    }
    room.live_buffer.append(text)
    await room.emit_caption(rec)
    now = time.time()
    if now - room.last_note_at > 18 and len(room.live_buffer) >= 3:
        room.last_note_at = now
        await room.emit_note(extractive_note(room.live_buffer))


async def run_demo() -> None:
    events = LECTURE["events"]
    t0 = time.time()
    try:
        for ev in events:
            delay = ev["at"] - (time.time() - t0)
            if delay > 0:
                await asyncio.sleep(delay)
            if ev["type"] == "caption":
                rec = {
                    "spk": ev["spk"],
                    "en": ev["en"],
                    "hi": ev["hi"],
                    "ta": ev["ta"],
                    "bn": ev["bn"],
                    "es": ev["es"],
                    "source": "demo",
                }
                await room.emit_caption(rec)
            elif ev["type"] == "note":
                await room.emit_note(
                    {"title": ev["title"], "bullets": ev["bullets"], "simple": ev["simple"]}
                )
            elif ev["type"] == "glossary":
                g = {"term": ev["term"], "def": ev["def"]}
                if not any(x["term"] == g["term"] for x in room.glossary):
                    room.glossary.append(g)
                    await room.broadcast({"type": "glossary", "entry": g})
            elif ev["type"] == "alert":
                alert = {
                    "id": uuid.uuid4().hex[:8],
                    "t": time.time(),
                    "kind": ev["kind"],
                    "label": ev["label"],
                    "en": ev["en"],
                }
                room.alerts.append(alert)
                await room.broadcast({"type": "alert", "alert": alert}, caption_priority=True)
        room.mode = "idle"
        await room.broadcast({"type": "ended", "state": room.snapshot()})
    except asyncio.CancelledError:
        return


if __name__ == "__main__":
    import os
    import uvicorn

    force_http = os.environ.get("LEKHA_HTTP", "").lower() in ("1", "true", "yes")
    cert = ROOT / "certs" / "cert.pem"
    key = ROOT / "certs" / "key.pem"
    ssl = {}
    if not force_http and cert.exists() and key.exists():
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        print("Lekha HTTPS  →  https://localhost:8005")
        print("Chrome: Advanced → Proceed to localhost (self-signed cert). Then allow the mic.")
    else:
        print("Lekha HTTP   →  http://localhost:8005")
    uvicorn.run(app, host="0.0.0.0", port=8005, reload=False, **ssl)
