import time
from typing import Callable, List

from config import load_config
from item import ClipItem

from .base import Plugin

HTML_TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body { margin: 0; font-family: __FONT__; font-size: 14pt; background: __HEX__; color: __FG__; transition: color 120ms ease; }
    .wrap { padding: 12px; display: flex; gap: 16px; align-items: stretch; }
    .left { width: 220px; display: flex; flex-direction: column; gap: 10px; }
    .swatch-split { display: flex; flex-direction: column; gap: 6px; min-height: 125px; }
    .swatch {
      flex: 1;
      border-radius: 12px;
      border: none;
      padding: 10px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      background: __HEX__;
      color: __FG__;
      box-shadow: inset 0 0 0 1px rgba(0,0,0,0.08);
    }
    .label { font-size: 11pt; opacity: 0.8; margin-bottom: 2px; }
    .hex { font-size: 11pt; font-weight: 700; letter-spacing: 0.5px; }
    .rgb { font-size: 11pt; opacity: 0.9; }
    #hue {
      width: 100%;
      height: 16px;
      border-radius: 8px;
      border: none;
      display: block;
    }
    .right {
      flex: 1;
      min-width: 200px;
      display: flex;
      align-items: center;
    }
    #sv {
      width: 100%;
      height: 150px;
      border-radius: 12px;
      border: none;
      display: block;
    }
    canvas { cursor: crosshair; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="left">
      <div class="swatch-split">
        <div id="last" class="swatch">
          <div id="lastHex" class="hex">#FFFFFF</div>
          <div id="lastRgb" class="rgb">rgb(255, 255, 255)</div>
        </div>
        <div id="swatch" class="swatch">
          <div id="hex" class="hex">#FFFFFF</div>
          <div id="rgb" class="rgb">rgb(255, 255, 255)</div>
        </div>
      </div>
      <canvas id="hue"></canvas>
    </div>
    <div class="right">
      <canvas id="sv"></canvas>
    </div>
  </div>
  <script>
    const sv = document.getElementById('sv');
    const hue = document.getElementById('hue');
    const hexEl = document.getElementById('hex');
    const rgbEl = document.getElementById('rgb');
    const swatch = document.getElementById('swatch');
    const lastSwatch = document.getElementById('last');
    const lastHex = document.getElementById('lastHex');

    const svCtx = sv.getContext('2d');
    const hueCtx = hue.getContext('2d');

    const initialHex = "__HEX__";
    function hexToHsv(hex) {
      let v = hex.replace('#','');
      if (v.length === 3) v = v[0]+v[0]+v[1]+v[1]+v[2]+v[2];
      if (v.length !== 6) return {h: 0, s: 0, v: 1};
      const r = parseInt(v.slice(0,2),16)/255;
      const g = parseInt(v.slice(2,4),16)/255;
      const b = parseInt(v.slice(4,6),16)/255;
      const max = Math.max(r,g,b), min = Math.min(r,g,b);
      const d = max - min;
      let h = 0;
      if (d !== 0) {
        if (max === r) h = ((g - b) / d + (g < b ? 6 : 0));
        else if (max === g) h = ((b - r) / d + 2);
        else h = ((r - g) / d + 4);
        h /= 6;
      }
      const s = max === 0 ? 0 : d / max;
      return {h, s, v: max};
    }

    let h = 50 / 360, s = 1, v = 1; // defaults, replaced by initialHex below
    let lastColor = initialHex;

    function clamp(v, min=0, max=1) { return Math.min(max, Math.max(min, v)); }

    function hsvToRgb(h, s, v) {
      let r, g, b;
      let i = Math.floor(h * 6);
      let f = h * 6 - i;
      let p = v * (1 - s);
      let q = v * (1 - f * s);
      let t = v * (1 - (1 - f) * s);
      switch (i % 6) {
        case 0: r = v; g = t; b = p; break;
        case 1: r = q; g = v; b = p; break;
        case 2: r = p; g = v; b = t; break;
        case 3: r = p; g = q; b = v; break;
        case 4: r = t; g = p; b = v; break;
        case 5: r = v; g = p; b = q; break;
      }
      return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
    }

    function rgbToHex(r,g,b) {
      const toHex = (x)=>x.toString(16).padStart(2,'0').toUpperCase();
      return '#' + toHex(r) + toHex(g) + toHex(b);
    }
    
    function hexToRgb(hex) {
      let v = hex.replace('#','');
      if (v.length === 3) v = v[0]+v[0]+v[1]+v[1]+v[2]+v[2];
      if (v.length !== 6) return [255,255,255];
      const r = parseInt(v.slice(0,2),16);
      const g = parseInt(v.slice(2,4),16);
      const b = parseInt(v.slice(4,6),16);
      return [r,g,b];
    }

    function redrawSV() {
      const {width, height} = sv;
      const hueGrad = svCtx.createLinearGradient(0, 0, width, 0);
      const [r, g, b] = hsvToRgb(h, 1, 1);
      hueGrad.addColorStop(0, '#fff');
      hueGrad.addColorStop(1, rgbToHex(r,g,b));
      svCtx.fillStyle = hueGrad;
      svCtx.fillRect(0, 0, width, height);
      const valGrad = svCtx.createLinearGradient(0, 0, 0, height);
      valGrad.addColorStop(0, 'rgba(0,0,0,0)');
      valGrad.addColorStop(1, 'rgba(0,0,0,1)');
      svCtx.fillStyle = valGrad;
      svCtx.fillRect(0, 0, width, height);
    }

    function redrawHue() {
      const {width, height} = hue;
      const grad = hueCtx.createLinearGradient(0,0,width,0);
      grad.addColorStop(0.0, '#ff0000');
      grad.addColorStop(0.17, '#ffff00');
      grad.addColorStop(0.34, '#00ff00');
      grad.addColorStop(0.50, '#00ffff');
      grad.addColorStop(0.67, '#0000ff');
      grad.addColorStop(0.84, '#ff00ff');
      grad.addColorStop(1.0, '#ff0000');
      hueCtx.fillStyle = grad;
      hueCtx.fillRect(0,0,width,height);
    }

    function updateOutput() {
      const [r,g,b] = hsvToRgb(h, s, v);
      const hex = rgbToHex(r,g,b);
      hexEl.textContent = hex.toUpperCase();
      rgbEl.textContent = `rgb(${r}, ${g}, ${b})`;
      const lum = (0.299*r + 0.587*g + 0.114*b)/255;
      const fg = lum > 0.6 ? '#0d1117' : '#e6edf3';
      document.body.style.color = fg;
      swatch.style.background = hex;
      swatch.style.color = fg;
      if (lastColor) {
        lastSwatch.style.background = lastColor;
        const lc = lastColor;
        const llum = (0.299*parseInt(lc.slice(1,3),16) + 0.587*parseInt(lc.slice(3,5),16) + 0.114*parseInt(lc.slice(5,7),16)) / 255;
        lastSwatch.style.color = llum > 0.6 ? '#0d1117' : '#e6edf3';
        lastHex.textContent = lastColor;
        const [lr, lg, lb] = hexToRgb(lastColor);
        lastRgb.textContent = `rgb(${lr}, ${lg}, ${lb})`;
      }
    }

    function pickSV(evt) {
      const rect = sv.getBoundingClientRect();
      const x = clamp((evt.clientX - rect.left) / rect.width);
      const y = clamp((evt.clientY - rect.top) / rect.height);
      s = x;
      v = 1 - y;
      updateOutput();
    }

    function pickHue(evt) {
      const rect = hue.getBoundingClientRect();
      const x = clamp((evt.clientX - rect.left) / rect.width);
      h = x;
      redrawSV();
      updateOutput();
    }

    function resize() {
      sv.width = sv.clientWidth;
      sv.height = sv.clientHeight;
      hue.width = hue.clientWidth;
      hue.height = hue.clientHeight;
      redrawHue();
      redrawSV();
      updateOutput();
    }

    function startDrag() {
      lastColor = hexEl.textContent || lastColor;
      lastSwatch.style.display = "flex";
    }

    sv.addEventListener('mousedown', (e)=>{ startDrag(); pickSV(e); sv.onmousemove = pickSV; });
    window.addEventListener('mouseup', ()=>{
      sv.onmousemove = null;
      lastColor = hexEl.textContent || lastColor;
      lastSwatch.style.display = "none";
      updateOutput();
    });
    hue.addEventListener('mousedown', (e)=>{ startDrag(); pickHue(e); hue.onmousemove = pickHue; });
    window.addEventListener('mouseup', ()=>{
      hue.onmousemove = null;
      lastColor = hexEl.textContent || lastColor;
      lastSwatch.style.display = "none";
      updateOutput();
    });

    window.addEventListener('resize', resize);

    (function initFromHex(){
      const hsv = hexToHsv(initialHex);
      h = hsv.h; s = hsv.s; v = hsv.v;
      const lum = (0.299*parseInt(initialHex.slice(1,3),16) + 0.587*parseInt(initialHex.slice(3,5),16) + 0.114*parseInt(initialHex.slice(5,7),16)) / 255;
      document.body.style.color = lum > 0.6 ? '#0d1117' : '#e6edf3';
      lastColor = initialHex;
      lastSwatch.style.display = "none";
      resize();
    })();

    window.cl_pPayload = function() {
      const hex = (document.getElementById('hex')?.textContent || '').trim().toUpperCase();
      return {
        hex: hex,
        rgb: (document.getElementById('rgb')?.textContent || '').trim(),
        html: document.documentElement.outerHTML
      };
    };
  </script>
</body>
</html>
"""


class ColorPickerPlugin(Plugin):
    plugin_id = "colorpicker"
    display_name = "Color Picker"

    def __init__(
        self,
        group_id: int,
        refresh_callback: Callable[[], None],
    ) -> None:
        super().__init__(group_id)
        self._refresh_callback = refresh_callback

    def build_items(self, clipboard_text: str) -> List[ClipItem]:
        now = int(time.time())
        default_hex = "#FACC15"
        fg = "#0d1117"
        font_family = (
            load_config().get("ui", {}).get("fontFamily")
            or "Cascadia Code, 'Segoe UI', sans-serif"
        )
        html = (
            HTML_TEMPLATE.replace("__HEX__", default_hex)
            .replace("__FG__", fg)
            .replace("__FONT__", font_family)
        )
        actions = [
            {"id": "copy_hex", "text": "Paste as HEX"},
            {"id": "copy_rgb", "text": "Paste as RGB"},
            {"id": "copy_hsl", "text": "Paste as HSL"},
            # {"id": "copy_html", "text": "Paste RAW HTML"},
        ]
        return [
            ClipItem(
                id=-1000,
                content_type="html",
                content_text=default_hex,
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="Color Picker",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=180,
                expanded_height=180,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=actions,
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        if not action_id:
            return False
        payload = payload or {}
        hex_value = str(payload.get("hex") or payload.get("color") or "").strip()
        rgb_value = str(payload.get("rgb") or "").strip()
        html_value = payload.get("html")

        # Fallback to stored base color
        if not hex_value:
            hex_value = backend.getPluginBaseColor(self.plugin_id) or "#FACC15"
        hex_value = hex_value.upper()

        if action_id == "copy_hex":
            backend.plugin_set_clipboard_and_paste(hex_value)
            return True

        if action_id == "copy_rgb":
            if not rgb_value:
                try:
                    r = int(hex_value[1:3], 16)
                    g = int(hex_value[3:5], 16)
                    b = int(hex_value[5:7], 16)
                    rgb_value = f"rgb({r}, {g}, {b})"
                except Exception:
                    rgb_value = ""
            if rgb_value:
                backend.plugin_set_clipboard_and_paste(rgb_value)
                return True
            return False
        if action_id == "copy_hsl":
            if not rgb_value:
                try:
                    r = int(hex_value[1:3], 16) / 255.0
                    g = int(hex_value[3:5], 16) / 255.0
                    b = int(hex_value[5:7], 16) / 255.0
                    max_c = max(r, g, b)
                    min_c = min(r, g, b)
                    l = (max_c + min_c) / 2.0
                    if max_c == min_c:
                        h = s = 0.0
                    else:
                        d = max_c - min_c
                        s = (
                            d / (2.0 - max_c - min_c)
                            if l > 0.5
                            else d / (max_c + min_c)
                        )
                        if max_c == r:
                            h = (g - b) / d + (6 if g < b else 0)
                        elif max_c == g:
                            h = (b - r) / d + 2
                        else:
                            h = (r - g) / d + 4
                        h /= 6.0
                    h_deg = round(h * 360)
                    s_perc = round(s * 100)
                    l_perc = round(l * 100)
                    rgb_value = f"hsl({h_deg}, {s_perc}%, {l_perc}%)"
                except Exception:
                    rgb_value = ""
            if rgb_value:
                backend.plugin_set_clipboard_and_paste(rgb_value)
                return True
            return False

        if action_id == "copy_html":
            if not html_value:
                html_value = f"<body bgcolor='{hex_value}'></body>"
            backend.plugin_set_clipboard_and_paste(str(html_value))
            return True

        return False
