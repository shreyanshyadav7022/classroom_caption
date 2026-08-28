# Lekha (लेखा) — low-bandwidth lecture captions

Hackathon prototype of the *Low-Bandwidth Real-Time Lecture Captioning & Multilingual Notes* design.

**Thesis:** text is cheap, audio/video is expensive. Do ASR / notes / translation on one classroom edge device. Student phones only ever receive JSON.

## Run

```bash
cd lekha
pip install fastapi "uvicorn[standard]" python-multipart
python3 server.py
```

Open **HTTPS** (needed for the microphone in Chrome). Use **localhost**, never `0.0.0.0`:

- Home — https://localhost:8005/
- **Edge console (teacher)** — https://localhost:8005/teacher
- **Student PWA** — https://localhost:8005/student

The first time Chrome says “Not private” because the cert is local. On a Mac, **trust it once**:

```bash
chmod +x trust-mac.sh
./trust-mac.sh
```

Then **Cmd+Q** Chrome (fully quit) and reopen https://localhost:8005/teacher.

Or by hand: open `certs/cert.pem` → Keychain Access → System keychain → double-click the cert → Trust → **Always Trust**. Quit Chrome and reopen.

## Demo script (3 minutes)

1. Open teacher + student side by side.
2. On the student, join as **Priya**, language **हिन्दी**, check *deaf / hard of hearing*.
3. Optionally open a third tab as **Arjun** in English — Job C should fan out only to subscribed languages.
4. On the teacher, hit **Run demo lecture**.
5. Point at:
   - Job A packets in the wire log (~40–80 bytes).
   - The “if we had streamed audio” counter vs. text sent.
   - Hindi cinema captions + QoS 2 on Priya.
   - Rolling notes / glossary landing on the Notes tab.
   - Laughter + period-bell visual alerts (phone vibrates if hearing-impaired).
6. Toggle the student language live — subscribe-based MT, no extra audio.
7. Download `notes.md` — this is the end-of-day LMS burst.

**Live mic:** Chrome/Edge, **Live mic** on the teacher. Browser Web Speech API stands in for Whisper.cpp. Hindi is a tiny on-device lexicon (NLLB stand-in); demo lecture uses human translations.

## What is real vs. simulated

| Design piece | In this prototype |
|---|---|
| Local Wi-Fi, text-only WebSocket | Real |
| Subscribe-based translation fan-out | Real |
| QoS: hearing-impaired students first | Real (send order) |
| PWA cache / IndexedDB-style localStorage | Real |
| Packet size vs. 16 kbps audio meter | Real accounting |
| Whisper.cpp / Silero VAD / NLLB / Phi-3 | Simulated (scripted lecture + Web Speech + lexicon) |
| MQTT | WebSocket with the same payload shape |

That split is intentional: a Pi 5 with quantized Whisper is the production edge; the hackathon laptop should still *show the architecture working*.

## Stack

Python FastAPI + WebSockets, vanilla PWA (no build step). Target hardware in production: Raspberry Pi 5 / teacher laptop; students: any phone browser.
