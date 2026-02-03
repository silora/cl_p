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
    }
    button.key.op { color: #0284c7; background: #f3f8ff; }
    button.key.action { color: #d97706; background: #fff7ed; }
    button.key.equals { background: #0ea5e9; color: #ffffff; grid-column: span 2; }
    button.key:hover { filter: brightness(0.98); }
    button.key:active { transform: translateY(1px); }
    .info {
      color: #6b7280;
      font-size: 13px;
      line-height: 1.5;
      grid-column: 1 / -1;
    }
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

    <div class="keypad">
      <button class="key action" data-key="C">AC</button>
      <button class="key op" data-key="(">(</button>
      <button class="key op" data-key=")">)</button>
      <button class="key op" data-key="%">%</button>
      <button class="key op" data-key="^">^</button>
      <button class="key action" data-key="Backspace">?</button>

      <button class="key op" data-key="sin(">sin</button>
      <button class="key op" data-key="cos(">cos</button>
      <button class="key op" data-key="tan(">tan</button>
      <button class="key op" data-key="ln(">ln</button>
      <button class="key op" data-key="log(">log</button>
      <button class="key op" data-key="sqrt(">sqrt</button>

      <button class="key" data-key="7">7</button>
      <button class="key" data-key="8">8</button>
      <button class="key" data-key="9">9</button>
      <button class="key op" data-key="/">//button>
      <button class="key op" data-key="/">/</button>
      <button class="key op" data-key="e">e</button>

      <button class="key" data-key="4">4</button>
      <button class="key" data-key="5">5</button>
      <button class="key" data-key="6">6</button>
      <button class="key op" data-key="*">*</button>
      <button class="key op" data-key="^2">x^2</button>
      <button class="key op" data-key="^2">x^2</button>

      <button class="key" data-key="1">1</button>
      <button class="key" data-key="2">2</button>
      <button class="key" data-key="3">3</button>
      <button class="key op" data-key="+">+</button>
      <button class="key op" data-key="fact(">n!</button>
      <button class="key action" data-key="ANS">ANS</button>

      <button class="key" data-key="0">0</button>
      <button class="key" data-key="00">0</button>
      <button class="key" data-key=".">.</button>
      <button class="key op" data-key="-">-</button>
      <button class="key equals" data-key="=">=</button>
    </div>
  </div>

  <script>
    const expr = document.getElementById("expr");
    const resEl = document.getElementById("res");
    let lastResult = "0";

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
        let r = 1;
        for (let i = 2; i <= Math.floor(n); i++) r *= i;
        return r;
      },
    };

    function sanitize(raw) {

      // Allow digits, operators, parentheses, commas, dot, letters for known funcs.
      if (!/^[0-9+\-*/%^()., A-Za-z]*$/.test(raw)) {
        throw new Error("Invalid character");
      }
      return raw.replace(/\^/g, "**");
    }
    function deleteAtCaret() {
      expr.focus();
      const start = expr.selectionStart ?? expr.value.length;
      const end = expr.selectionEnd ?? start;
      if (start !== end) {
        const next = expr.value.slice(0, start) + expr.value.slice(end);
        expr.value = next;
        expr.setSelectionRange(start, start);
        return;
      }
      if (start === 0) return;
      const newPos = start - 1;
      expr.value = expr.value.slice(0, newPos) + expr.value.slice(start);
      expr.setSelectionRange(newPos, newPos);
    }

    // Ensure caret starts at the end after load.
    setTimeout(() => {
      expr.focus();
      const len = expr.value.length;
      expr.setSelectionRange(len, len);
    }, 0);


      const raw = (expr.value || "").trim();
      if (!raw) {
        setResult("0");
        return;
      }
      try {
        const cleaned = sanitize(raw);
        const argNames = Object.keys(fnMap);
        const argValues = Object.values(fnMap);
        const fn = new Function(...argNames, `"use strict"; return (${cleaned});`);
        const val = fn(...argValues);
        setResult(String(val));
      } catch (e) {
        setError(e.message || "Error");
      }
    }


    function setResult(txt) {
      lastResult = txt;
      resEl.textContent = txt;
      resEl.classList.remove("err");
    }
    function setError(msg) {
      // Preserve lastResult when error; just show message visually.
      resEl.textContent = msg;
      resEl.classList.add("err");
    }

    function handleKey(key) {
      if (key === "=" || key === "Enter") {
        compute();
        return;
      }

      let handled = true;
      if (key === "00") {
        expr.value += "00";
      } else if (key === "C") {
        expr.value = "";
        setResult("0");
      } else if (key === "Backspace") {
        deleteAtCaret();
      } else if (key === "ANS") {
        expr.value += lastResult || "";
      } else if (key === "^2") {
        expr.value += "^2";
      } else if (key.length === 1 || key.endsWith("(")) {
        expr.value += key;
      } else {
        handled = false;
      }

      if (handled) compute();
    }

    document.querySelectorAll("button.key").forEach((btn) => {
      btn.addEventListener("click", () => {
        const k = btn.dataset.key || "";
        if (k === "=") {
          compute();
          return;
        }
        handleKey(k);
      });
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

    expr.addEventListener("input", () => {
      compute();
    });

    document.addEventListener(
      "keydown",
      (e) => {
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
          deleteAtCaret();
          compute();
          return;
        }
        if (e.key && e.key.length === 1) {
          e.preventDefault();
          expr.focus();
          expr.value += e.key;
          // place caret at end
          const len = expr.value.length;
          expr.setSelectionRange(len, len);
          compute();
        }
      },
      { capture: true }
    );

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
