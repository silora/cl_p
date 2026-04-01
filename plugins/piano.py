import time
from typing import Callable, List

from config import load_config
from item import ClipItem

from .base import Plugin


def _font_family() -> str:
    return (
        load_config().get("ui", {}).get("fontFamily")
        or "Cascadia Code, 'Segoe UI', sans-serif"
    )


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: __FONT__;
      background: #ffcbf2;
      color: #2a1f2f;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }
    .layout {
      width: min(720px, 96vw);
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 6px 8px 10px 8px;
    }
    .controls {
      display: flex;
      gap: 4px;
      align-items: center;
      justify-content: center;
      position: relative;
      z-index: 3;
      margin-bottom: 4px;
    }
    .btn {
      border: none;
      background: #e5b3fe;
      color: #2a1f2f;
      border-radius: 9px;
      padding: 5px 9px;
      font-weight: 700;
      font-size: 16px;
      font-family: inherit;
      cursor: pointer;
      box-shadow: 0 6px 16px rgba(42,31,47,0.2);
      transition: transform 60ms ease, filter 80ms ease;
    }
    .btn:hover { filter: brightness(1.05); }
    .btn:active { transform: translateY(2px); filter: brightness(0.93); }
    .btn.rec { background: #e2afff; }
    .btn.rec.on { background: #e63946; color: #fff; box-shadow: 0 6px 16px rgba(230,57,70,0.35); }
    .wave-rail {
      display: inline-flex;
      background: #ecbcfd;
      border-radius: 10px;
      padding: 3px;
      box-shadow: 0 6px 16px rgba(42,31,47,0.14);
      gap: 3px;
    }
    .wave-opt {
      border: none;
      background: transparent;
      color: #2a1f2f;
      border-radius: 7px;
      padding: 5px 8px;
      font-size: 15px;
      font-weight: 700;
      font-family: inherit;
      cursor: pointer;
      transition: background 100ms ease, color 100ms ease;
    }
    .wave-opt.active {
      background: #deaaff;
      color: #2a1f2f;
      box-shadow: 0 2px 6px rgba(42,31,47,0.15);
    }
    .pill {
      border: none;
      background: #deaaff;
      color: #2a1f2f;
      border-radius: 9px;
      padding: 5px 9px;
      font-size: 14px;
      min-width: 48px;
      text-align: center;
      font-family: inherit;
    }
    .keys-card {
      width: 100%;
      background: #fdf7ff;
      border: 1px solid #e8c7ff;
      border-radius: 14px;
      padding: 10px 10px 14px 10px;
      box-shadow: 0 10px 22px rgba(42,31,47,0.12);
    }
    .keys { position: relative; width: 100%; height: 110px; z-index: 1; }
    .white {
      position: absolute;
      bottom: 0;
      background: linear-gradient(180deg, #fdf7ff, #f3c4fb);
      border: 1px solid #e2afff;
      border-radius: 0 0 10px 10px;
      box-shadow: 0 8px 18px rgba(42,31,47,0.15);
      display: flex;
      align-items: flex-end;
      justify-content: center;
      font-weight: 600;
      color: #2a1f2f;
      cursor: pointer;
      user-select: none;
      transition: transform 40ms ease, filter 80ms ease;
    }
    .white.active { transform: translateY(2px); filter: brightness(0.93); }
    .black {
      position: absolute;
      top: 0;
      background: linear-gradient(180deg, #d8bbff, #c0fdff);
      border: 1px solid #c8e7ff;
      border-radius: 0 0 10px 10px;
      box-shadow: 0 6px 12px rgba(42,31,47,0.32);
      color: #2a1f2f;
      display: grid;
      place-items: end center;
      padding-bottom: 8px;
      font-weight: 600;
      cursor: pointer;
      user-select: none;
      transition: transform 40ms ease, filter 80ms ease;
    }
    .black.active { transform: translateY(2px); filter: brightness(1.1); }
  </style>
</head>
<body bgcolor="#ffcbf2">
  <div class="layout">
    <div class="controls">
      <button class="btn" id="octDown">▼▼</button>
      <div class="pill" id="octLabel">0</div>
      <button class="btn" id="octUp">▲▲</button>
      <button class="btn" id="down">▼</button>
      <div class="pill" id="transposeLabel">0</div>
      <button class="btn" id="up">▲</button>
      <div class="wave-rail" id="waveRail">
        <button class="wave-opt active" data-wave="sine" title="Sine" aria-label="Sine wave">∿</button>
        <button class="wave-opt" data-wave="triangle" title="Triangle" aria-label="Triangle wave">△</button>
        <button class="wave-opt" data-wave="square" title="Square" aria-label="Square wave">□</button>
        <button class="wave-opt" data-wave="sawtooth" title="Sawtooth" aria-label="Sawtooth wave">⧋</button>
      </div>
      <button class="btn rec" id="rec" aria-label="Record">●</button>
      <button class="btn" id="play">▶</button>
    </div>
    <div class="keys-card">
      <div class="keys" id="keys"></div>
    </div>
  </div>
  <script>
    const audio = new (window.AudioContext || window.webkitAudioContext)();
    const base = 261.63; // middle C
    const notes = [
      // Mapped Octave 1 (left hand)
      { name: "F4",  key: "A",  semitone: 5,  white: true },
      { name: "F#4", key: "W",  semitone: 6,  white: false },
      { name: "G4",  key: "S",  semitone: 7,  white: true },
      { name: "G#4", key: "E",  semitone: 8,  white: false },
      { name: "A4",  key: "D",  semitone: 9,  white: true },
      { name: "A#4", key: "R",  semitone: 10, white: false },
      { name: "B4",  key: "F",  semitone: 11, white: true },
      { name: "C5",  key: "G",  semitone: 12, white: true },
      { name: "C#5", key: "Y",  semitone: 13, white: false },
      { name: "D5",  key: "H",  semitone: 14, white: true },
      { name: "D#5", key: "U",  semitone: 15, white: false },
      { name: "E5",  key: "J",  semitone: 16, white: true },
      // Mapped Octave 2 (right hand, jkl;' + I/O/P for sharps)
      { name: "F5",  key: "K",  semitone: 17, white: true },
      { name: "F#5", key: "O",  semitone: 18, white: false },
      { name: "G5",  key: "L",  semitone: 19, white: true },
      { name: "G#5", key: "P",  semitone: 20, white: false },
      { name: "A5",  key: ";",  semitone: 21, white: true },
      { name: "A#5", key: "[",  semitone: 22, white: false },
      { name: "B5",  key: "'",  semitone: 23, white: true },
      // Click-only top notes
      { name: "C6",  key: null, semitone: 24, white: true },
      { name: "C#6", key: null, semitone: 25, white: false },
      { name: "D6",  key: null, semitone: 26, white: true },
      { name: "D#6", key: null, semitone: 27, white: false },
      { name: "E6",  key: null, semitone: 28, white: true },
      { name: "F6",  key: null, semitone: 29, white: true },
    ];
    const NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
    let transpose = 0; // semitone shift
    let octaveShift = 0; // in semitones, multiples of 12
    let waveType = "sine";
    let recording = false;
    // store absolute semitone values (relative to C4) plus millisecond offsets from start
    // so playback preserves pitch AND timing regardless of later transpose/octave changes.
    let recorded = [];
    let recordStart = 0;
    let playbackTimers = [];
    const keyMap = {};
    const gap = 4; // px between white keys
    const keysEl = document.getElementById("keys");
    const transposeLabel = document.getElementById("transposeLabel");
    const octLabel = document.getElementById("octLabel");
    const octUp = document.getElementById("octUp");
    const octDown = document.getElementById("octDown");
    const upBtn = document.getElementById("up");
    const downBtn = document.getElementById("down");
    const waveRail = document.getElementById("waveRail");
    const waveOpts = waveRail ? Array.from(waveRail.querySelectorAll(".wave-opt")) : [];
    const recBtn = document.getElementById("rec");
    const playBtn = document.getElementById("play");

    function freq(semitone) { return base * Math.pow(2, semitone / 12); }

    function semitoneFromName(label) {
      const m = String(label || "").match(/^([A-G])(#?)(\d+)$/i);
      if (!m) return null;
      const baseMap = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
      const letter = m[1].toUpperCase();
      const sharp = m[2] === "#" ? 1 : 0;
      const oct = parseInt(m[3], 10);
      const base = baseMap[letter];
      if (base === undefined || Number.isNaN(oct)) return null;
      return (oct - 4) * 12 + base + sharp;
    }

    function nearestNoteForSemi(semi) {
      let best = null;
      let bestDist = Infinity;
      notes.forEach((n) => {
        const dist = Math.abs(n.semitone - semi);
        if (dist < bestDist) {
          bestDist = dist;
          best = n;
        }
      });
      return best;
    }

    function semiToName(semi) {
      const idx = ((semi % 12) + 12) % 12;
      const oct = 4 + Math.floor(semi / 12);
      return `${NAMES[idx]}${oct}`;
    }

    function playAbsolute(semitone, name, el) {
      const now = audio.currentTime;
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = waveType;
      osc.frequency.value = freq(semitone);
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.exponentialRampToValueAtTime(0.2, now + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.9);
      osc.connect(gain).connect(audio.destination);
      osc.start(now);
      osc.stop(now + 1);
      if (el) { el.classList.add("active"); setTimeout(()=>el.classList.remove("active"), 120); }
      try { navigator.clipboard.writeText(name); } catch (e) { /* ignore */ }
    }

    function play(note, el) {
      const total = note.semitone + transpose + octaveShift;
      const name = semiToName(total);
      playAbsolute(total, name, el);
      if (recording) {
        const now = performance.now();
        recorded.push({ semi: total, time: now - recordStart });
      }
    }

    function render() {
      keysEl.innerHTML = "";
      const width = keysEl.clientWidth || 640;
      const height = keysEl.clientHeight || 140;

      // annotate notes with white indices for layout
      let whiteIdx = 0;
      notes.forEach((n) => {
        if (n.white) {
          n.whiteIndex = whiteIdx++;
        } else {
          n.prevWhite = Math.max(0, whiteIdx - 1);
        }
      });

      const whiteCount = whiteIdx;
      const keyW = (width - gap * (whiteCount - 1)) / whiteCount;
      const keyH = height;
      const blackH = Math.round(keyH * 0.55);
      const blackW = Math.round(keyW * 0.74);

      const whiteLefts = [];
      notes.forEach((n) => {
        if (!n.white) return;
        const idx = n.whiteIndex;
        const el = document.createElement("div");
        el.className = "white";
        el.textContent = n.key || n.name.replace(/\d/, "");
        el.style.width = `${keyW}px`;
        el.style.height = `${keyH}px`;
        const left = idx * (keyW + gap);
        whiteLefts[idx] = left;
        el.style.left = `${left}px`;
        el.onclick = () => play(n, el);
        keysEl.appendChild(el);
        if (n.key) keyMap[n.key.toLowerCase()] = el;
        n._el = el;
      });

      notes.forEach((n) => {
        if (n.white) return;
        const el = document.createElement("div");
        el.className = "black";
        el.textContent = n.key || n.name.replace(/\d/, "");
        const idx = n.prevWhite ?? 0;
        const left =
          (whiteLefts[idx] ?? 0) + keyW + gap / 2 - blackW / 2;
        el.style.width = `${blackW}px`;
        el.style.height = `${blackH}px`;
        el.style.left = `${left}px`;
        el.onclick = (e) => { e.stopPropagation(); play(n, el); };
        keysEl.appendChild(el);
        if (n.key) keyMap[n.key.toLowerCase()] = el;
        n._el = el;
      });
    }

    render();
    window.addEventListener("resize", () => render());

    function updateTransposeLabel() {
      const sign = transpose > 0 ? "+" : "";
      transposeLabel.textContent = `${sign}${transpose}`;
    }
    function nudgeTranspose(delta) {
      transpose = Math.max(-12, Math.min(12, transpose + delta));
      updateTransposeLabel();
    }
    upBtn.onclick = () => nudgeTranspose(1);
    downBtn.onclick = () => nudgeTranspose(-1);
    waveOpts.forEach((btn) => {
      btn.addEventListener("click", () => {
        waveOpts.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        waveType = btn.dataset.wave || "sine";
      });
    });
    function toggleRecord() {
      recording = !recording;
      if (recording) {
        recorded = [];
        recordStart = performance.now();
        recBtn.classList.add("on");
        recBtn.textContent = "⏺";
        recBtn.title = "Stop";
      } else {
        recBtn.classList.remove("on");
        recBtn.textContent = "⏺";
        recBtn.title = "Record";
      }
    }
    function stopPlayback() {
      playbackTimers.forEach((t) => clearTimeout(t));
      playbackTimers = [];
    }
    function playRecorded() {
      if (!recorded.length) return;
      stopPlayback();
      recorded.forEach(({ semi, time }) => {
        const timer = setTimeout(() => {
          const displayBaseSemi = semi - transpose - octaveShift;
          const target =
            notes.find(n => n.semitone === displayBaseSemi) ||
            nearestNoteForSemi(displayBaseSemi);
          playAbsolute(
            semi,
            semiToName(semi),
            (target || {})._el || null
          );
        }, time);
        playbackTimers.push(timer);
      });
    }
    recBtn.onclick = toggleRecord;
    playBtn.onclick = playRecorded;
    updateTransposeLabel();

    window.addEventListener("keydown", (e) => {
      const k = (e.key || "").toLowerCase();
      const note = notes.find(n => n.key && n.key.toLowerCase() === k);
      if (note) {
        e.preventDefault();
        play(note, note._el);
      }
    });

    window.cl_pPayload = function() {
      const seq = recorded.map((r) => semiToName(r.semi)).join(" ");
      return { note: null, sequence: seq };
    };
  </script>
</body>
</html>
"""


class PianoPlugin(Plugin):
    plugin_id = "piano"
    display_name = "Piano"
    uses_clipboard = False

    def __init__(
        self,
        group_id: int,
        refresh_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        html = HTML.replace("__FONT__", _font_family())
        return [
            ClipItem(
                id=-1000,
                content_type="html",
                content_text="Piano",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="Piano",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=200,
                expanded_height=200,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[
                    {"id": "paste_sequence", "text": "Paste played sequence"},
                ],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        if action_id == "paste_sequence":
            seq = ""
            if isinstance(payload, dict):
                seq = str(payload.get("sequence") or "").strip()
            if not seq:
                return False
            backend.plugin_set_clipboard_and_paste(seq)
            return True
        return False
