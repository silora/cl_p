import re
from typing import Optional


def truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + "..."


def normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.lower().startswith("www."):
        u = "http://" + u
    parsed = re.match(r"^(https?://)?(.*)$", u, flags=re.IGNORECASE)
    if parsed:
        scheme = parsed.group(1) or "http://"
        rest = parsed.group(2)
        u = scheme.lower() + rest
    # drop trailing slash to prevent dupes
    if u.endswith("/"):
        u = u[:-1]
    return u


def parse_color_text(text: str) -> Optional[str]:
    value = text.strip()
    if not value:
        return None
    hex_match = re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", value)
    if hex_match:
        base = hex_match.group(1)
        alpha = hex_match.group(2) or ""
        return f"#{(base + alpha).upper()}"
    rgb_match = re.fullmatch(
        r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
        value,
        re.IGNORECASE,
    )
    if rgb_match:
        r, g, b = (int(x) for x in rgb_match.groups())
        if all(0 <= v <= 255 for v in (r, g, b)):
            return f"rgb({r}, {g}, {b})"
    rgba_match = re.fullmatch(
        r"rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([0-9]*\.?[0-9]+)\s*\)",
        value,
        re.IGNORECASE,
    )
    if rgba_match:
        r, g, b = (int(x) for x in rgba_match.groups()[:3])
        alpha_raw = rgba_match.group(4)
        try:
            alpha_val = (
                float(alpha_raw)
                if "." in alpha_raw
                else float(
                    int(alpha_raw) / 255 if int(alpha_raw) > 1 else int(alpha_raw)
                )
            )
        except Exception:
            alpha_val = None
        if (
            all(0 <= v <= 255 for v in (r, g, b))
            and alpha_val is not None
            and 0 <= alpha_val <= 1
        ):
            alpha_norm = f"{alpha_val:.3f}".rstrip("0").rstrip(".")
            return f"rgba({r}, {g}, {b}, {alpha_norm})"
    return None
