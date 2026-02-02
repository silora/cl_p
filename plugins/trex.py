import time
from typing import Callable, List

from config import load_config
from item import ClipItem

from .base import Plugin


def _font_family() -> str:
    return (
        load_config()
        .get("ui", {})
        .get("fontFamily")
        or "Cascadia Code, 'Segoe UI', sans-serif"
    )


HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 0; font-family: __FONT__; background: #111; color: #e6edf3; }
  .wrap { padding: 8px; display: flex; flex-direction: column; gap: 6px; }
  .title { text-align: center; font-weight: 700; font-size: 14pt; }
  canvas { width: 100%; height: 160px; background: #191919; border-radius: 8px; border: 1px solid #333; }
  .hint { text-align: center; font-size: 10pt; color: #aaa; }
</style>
</head>
<body>
  <div class="wrap">
    <div class="title">T-Rex Runner</div>
    <canvas id="game" width="640" height="160"></canvas>
    <div class="hint">Space / ↑ to jump • ↓ to duck • R to restart</div>
  </div>
<script>
const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
let groundY = 130;
let trex = { x: 40, y: groundY, vy: 0, w: 26, h: 28, duck:false };
let gravity = 0.7;
let jumpV = -12;
let obstacles = [];
let frame = 0;
let speed = 6;
let alive = true;
let score = 0;

function reset() {
  obstacles = [];
  trex.y = groundY; trex.vy = 0; trex.duck=false;
  speed = 6; frame = 0; alive = true; score = 0;
}

function spawn() {
  const h = 20 + Math.random()*30;
  const w = 10 + Math.random()*15;
  obstacles.push({x: canvas.width + 20, w, h});
}

function update() {
  if (!alive) return;
  frame++;
  trex.vy += gravity;
  trex.y += trex.vy;
  if (trex.y > groundY) { trex.y = groundY; trex.vy = 0; }
  if (trex.duck) trex.h = 18; else trex.h = 28;

  if (frame % 80 === 0) spawn();
  obstacles.forEach(o => o.x -= speed);
  obstacles = obstacles.filter(o => o.x + o.w > 0);

  // collisions
  for (const o of obstacles) {
    if (trex.x < o.x + o.w &&
        trex.x + trex.w > o.x &&
        trex.y < groundY &&
        trex.y + trex.h > groundY - o.h) {
      alive = false;
    }
  }
  score += 1;
  speed = 6 + Math.min(6, score / 400);
}

function draw() {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle = "#2c2c2c";
  ctx.fillRect(0,groundY+trex.h-28,canvas.width,2);

  // trex
  ctx.fillStyle = "#f8e45c";
  ctx.fillRect(trex.x, trex.y - trex.h + 28, trex.w, trex.h);

  // obstacles
  ctx.fillStyle = "#e85d75";
  obstacles.forEach(o => {
    ctx.fillRect(o.x, groundY - o.h + trex.h - 28, o.w, o.h);
  });

  ctx.fillStyle = "#aaa";
  ctx.font = "12px __FONT__";
  ctx.fillText("Score: " + score.toString(), 520, 20);
  if (!alive) {
    ctx.font = "18px __FONT__";
    ctx.fillText("Game Over — press R to restart", 170, 80);
  }
}

function tick() {
  update();
  draw();
  requestAnimationFrame(tick);
}

document.addEventListener('keydown', (e)=>{
  if (e.code === "Space" || e.code === "ArrowUp") {
    if (trex.y >= groundY - 0.1 && alive) trex.vy = jumpV;
    e.preventDefault();
  }
  if (e.code === "ArrowDown") trex.duck = true;
  if (e.code === "KeyR") { reset(); }
});
document.addEventListener('keyup', (e)=>{
  if (e.code === "ArrowDown") trex.duck = false;
});

reset();
tick();
</script>
</body>
</html>
"""


class TrexPlugin(Plugin):
    plugin_id = "trex"
    display_name = "T-Rex Runner"
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
                content_text="T-Rex Runner",
                content_blob=html.encode("utf-8"),
                created_at=now,
                pinned=False,
                pinned_at=None,
                group_id=self.group_id,
                preview_text="Play the T-Rex game",
                preview_blob=None,
                has_full_content=True,
                content_length=len(html),
                collapsed_height=240,
                expanded_height=260,
                render_mode="web",
                plugin_id=self.plugin_id,
                extra_actions=[],
            )
        ]

    def on_action(self, action_id: str, backend, payload=None) -> bool:
        return False
