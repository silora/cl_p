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
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: __FONT__;
      background: #f5f7fb;
      color: #1f2933;
      display: grid;
      place-items: center;
      min-height: 100vh;
    }
    .frame {
      width: min(780px, 98vw);
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 18px;
      padding: 12px;
      box-shadow: 0 12px 32px rgba(0,0,0,0.08);
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
    }
    .display {
      background: #f0f2f7;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      grid-column: 1 / -1;
    }
    .label { color: #6b7280; font-size: 12px; letter-spacing: 0.3px; }
    #expr {
      background: transparent;
      border: none;
      color: #111827;
      font-size: 18px;
      width: 100%;
      outline: none;
    }
    #res {
      font-size: 26px;
      color: #0ea5e9;
      min-height: 30px;
      word-break: break-all;
    }
    .err { color: #dc2626; }

    .keypad {
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      grid-auto-rows: 40px; /* consistent row height so "=" can span cleanly */
      gap: 10px;
    }
    button.key {
      border: 1px solid #e5e7eb;
      background: #ffffff;
      color: #111827;
      border-radius: 10px;
      padding: 12px 10px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 10px rgba(15,23,42,0.06);
      transition: transform 80ms ease, filter 80ms ease;
      user-select: none;
      height: 100%;
    }
    button.key.op { color: #0284c7; background: #f3f8ff; }
    button.key.action { color: #d97706; background: #fff7ed; }
    button.key.equals { background: #0ea5e9; color: #ffffff; }
    button.key.wide { grid-column: span 2; }
    button.key.tall { grid-row: span 2; } /* "=" fills block beneath */
    button.key:hover { filter: brightness(0.98); }
    button.key:active { transform: translateY(1px); }
    code { background: #e5e7eb; padding: 2px 4px; border-radius: 6px; }
  </style>
</head>
<body bgcolor="#f3f5f9">
  <div class="frame">
    <div class="display">
      <div class="label">Expression (use keyboard or keypad)</div>
      <input id="expr" placeholder="e.g.: sin(0.5)+2^3" autofocus />
      <div class="label">Result</div>
      <div id="res">0</div>
    </div>

    <!-- 6-col layout, + - * / stacked in column 4, DEL at top-right, "=" spans two rows -->
    <div class="keypad">
      <!-- Row 1 -->
      <button class="key action" data-key="C">AC</button>
      <button class="key op" data-key="(">(</button>
      <button class="key op" data-key=")">)</button>
      <!-- move DEL to col4 -->
      <button class="key action" data-key="Backspace" style="grid-column:4">DEL</button>
      <button class="key op" data-key="%">%</button>
      <button class="key op" data-key="pi">π</button>

      <!-- Row 2 -->
      <button class="key op" data-key="sin(">sin</button>
      <button class="key op" data-key="cos(">cos</button>
      <button class="key op" data-key="tan(">tan</button>
      <button class="key op" data-key="+" style="grid-column:4">+</button>
      <button class="key op" data-key="ln(">ln</button>
      <button class="key op" data-key="log(">log</button>

      <!-- Row 3 -->
      <button class="key" data-key="7">7</button>
      <button class="key" data-key="8">8</button>
      <button class="key" data-key="9">9</button>
      <button class="key op" data-key="-" style="grid-column:4">−</button>
      <button class="key op" data-key="e">e</button>
      <button class="key op" data-key="^">xʸ</button>

      <!-- Row 4 -->
      <button class="key" data-key="4">4</button>
      <button class="key" data-key="5">5</button>
      <button class="key" data-key="6">6</button>
      <button class="key op" data-key="*" style="grid-column:4">×</button>
      <button class="key op" data-key="^2">x²</button>
      <button class="key op" data-key="inv">1/x</button>

      <!-- Row 5 -->
      <button class="key" data-key="1">1</button>
      <button class="key" data-key="2">2</button>
      <button class="key" data-key="3">3</button>
      <button class="key op" data-key="/" style="grid-column:4">÷</button>
      <button class="key op" data-key="neg">±</button>
      <button class="key equals tall" data-key="=" style="grid-column:6; grid-row:5 / span 2">=</button>

      <!-- Row 6 (fully pinned so nothing falls through) -->
      <button class="key wide" data-key="0" style="grid-column:1 / span 2; grid-row:6">0</button>
      <button class="key" data-key="." style="grid-column:3; grid-row:6">.</button>
      <button class="key action" data-key="ANS" style="grid-column:4; grid-row:6">ANS</button>
      <button class="key" data-key="00" style="grid-column:5; grid-row:6">00</button>

    </div>
  </div>

  <script>
    const expr = document.getElementById("expr");
    const resEl = document.getElementById("res");
    let lastResult = "0";

    // --- caret tracking so DEL works even after button click steals focus ---
    let lastSelStart = 0;
    let lastSelEnd = 0;

    function syncCaret() {
      if (document.activeElement === expr) {
        lastSelStart = expr.selectionStart ?? expr.value.length;
        lastSelEnd = expr.selectionEnd ?? lastSelStart;
      }
    }
    ["keyup", "click", "focus", "input", "mouseup", "select", "blur"].forEach((ev) =>
      expr.addEventListener(ev, syncCaret)
    );

    const fnMap = {
      sin: Math.sin,
      cos: Math.cos,
      tan: Math.tan,
      sqrt: Math.sqrt,
      ln: Math.log,
      log: (x) => Math.log10(x),
      pi: Math.PI,
      e: Math.E,
      fact: (n) => {
        n = Number(n);
        if (!Number.isFinite(n) || n < 0) throw new Error("Factorial requires non-negative integer");
        if (Math.floor(n) !== n) throw new Error("Factorial requires an integer");
        let r = 1;
        for (let i = 2; i <= n; i++) r *= i;
        return r;
      },
    };

    function setResult(txt) {
      lastResult = txt;
      resEl.textContent = txt;
      resEl.classList.remove("err");
    }
    function setError(msg) {
      resEl.textContent = msg;
      resEl.classList.add("err");
    }

    function sanitize(raw) {
      // Allow digits, operators, parentheses, commas, dot, spaces, letters.
      if (!/^[0-9+\-*/%^()., A-Za-z]*$/.test(raw)) {
        throw new Error("Invalid character");
      }
      return raw.replace(/\^/g, "**");
    }

    function compute() {
      const raw = (expr.value || "").trim();
      if (!raw) { setResult("0"); return; }
      try {
        const cleaned = sanitize(raw);
        const argNames = Object.keys(fnMap);
        const argValues = Object.values(fnMap);
        const fn = new Function(...argNames, `"use strict"; return (${cleaned});`);
        const val = fn(...argValues);
        setResult(String(val));
      } catch (e) {
        setError(e?.message || "Error");
      }
    }

    function deleteAtCaret() {
      // Use saved caret if focus was stolen by the button click
      const startSaved = lastSelStart;
      const endSaved = lastSelEnd;

      expr.focus();

      const start = (typeof startSaved === "number") ? startSaved : (expr.value.length);
      const end = (typeof endSaved === "number") ? endSaved : start;
      expr.setSelectionRange(start, end);

      if (start !== end) {
        expr.value = expr.value.slice(0, start) + expr.value.slice(end);
        expr.setSelectionRange(start, start);
        syncCaret();
        return;
      }
      if (start === 0) return;

      const newPos = start - 1;
      expr.value = expr.value.slice(0, newPos) + expr.value.slice(start);
      expr.setSelectionRange(newPos, newPos);
      syncCaret();
    }

    function handleKey(key) {
      if (key === "=" || key === "Enter") { compute(); return; }

      if (key === "C") { expr.value = ""; setResult("0"); syncCaret(); return; }

      if (key === "Backspace") {
        deleteAtCaret();
        compute();
        return;
      }

      if (key === "ANS") {
        expr.value += (lastResult || "0");
        syncCaret();
        compute();
        return;
      }

      if (key === "00") {
        expr.value += "00";
        syncCaret();
        compute();
        return;
      }

      if (key === "^2") {
        expr.value += "^2";
        syncCaret();
        compute();
        return;
      }

      // ± : wrap trailing number in (-n); if not applicable, insert "(-1)*"
      if (key === "neg") {
        const s = expr.value;
        const m = s.match(/(.*?)(\d+(\.\d+)?)(\s*)$/);
        if (m) expr.value = m[1] + "(-" + m[2] + ")" + m[4];
        else expr.value += "(-1)*";
        syncCaret();
        compute();
        return;
      }

      // 1/x : if empty -> "1/("; else append "^-1"
      if (key === "inv") {
        const s = (expr.value || "").trim();
        if (!s) expr.value = "1/(";
        else expr.value += "^-1";
        syncCaret();
        compute();
        return;
      }

      // default insert
      if (key.length === 1 || key.endsWith("(") || key === "^") {
        expr.value += key;
        syncCaret();
        compute();
      }
    }

    document.querySelectorAll("button.key").forEach((btn) => {
      btn.addEventListener("click", () => handleKey(btn.dataset.key || ""));
    });

    expr.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        compute();
        return;
      }
      if (e.key === "Backspace") {
        e.preventDefault();
        deleteAtCaret();
        compute();
        return;
      }
      // allow other keys; sanitize at compute time
    });

    expr.addEventListener("input", compute);

    document.addEventListener("keydown", (e) => {
      if (document.activeElement === expr) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.key === "Enter") {
        e.preventDefault();
        expr.focus();
        compute();
        return;
      }
      if (e.key === "Backspace") {
        e.preventDefault();
        expr.focus();
        deleteAtCaret();
        compute();
        return;
      }
      if (e.key && e.key.length === 1) {
        e.preventDefault();
        expr.focus();
        expr.value += e.key;
        const len = expr.value.length;
        expr.setSelectionRange(len, len);
        syncCaret();
        compute();
      }
    }, { capture: true });

    // Ensure caret starts at the end after load.
    setTimeout(() => {
      expr.focus();
      const len = expr.value.length;
      expr.setSelectionRange(len, len);
      syncCaret();
      compute();
    }, 0);

    // Expose result to the host for context-menu actions.
    window.cl_pPayload = () => lastResult || null;
  </script>
</body>
</html>
"""


class CalculatorPlugin(Plugin):
    plugin_id = "calculator"
    display_name = "Calculator"
    uses_clipboard = False

    def __init__(
        self,
        group_id: int,
        refresh_callback: Callable[[], None],
    ) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        font = _font_family()
        html = HTML.replace("__FONT__", font)
        return [
            ClipItem(
                id=-1000,
                content_type="html",
                content_text="Calculator",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="Calculator",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=495,
                expanded_height=495,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[
                    {"id": "paste_result", "text": "Paste current result"},
                ],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        if action_id == "paste_result":
            result = ""
            try:
                if payload:
                    result = str(payload)
            except Exception:
                result = ""
            if not result:
                return False
            backend.plugin_set_clipboard_and_paste(result)
            return True
        return False
