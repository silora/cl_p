import html as _html
import re
from pathlib import Path
from typing import Iterable, Optional


def truncate_html(html: str, limit: int) -> str:
    ## get "<style>...</style>" part
    style_parts = re.findall(r"(?is)<\s*style\b[^>]*>(.*?)</\s*style\s*>", html or "")
    limit += len("".join(style_parts))
    tokens = re.findall(r"<[^>]+>|[^<]+", html or "")
    result: list[str] = []
    stack: list[str] = []
    text_len = 0
    for tok in tokens:
        if tok.startswith("<"):
            if tok.startswith("</"):
                name = re.sub(r"[</>\\s].*$", "", tok[2:])
                if stack and stack[-1] == name:
                    stack.pop()
                result.append(tok)
                continue
            if tok.endswith("/>"):
                result.append(tok)
                continue
            name_match = re.match(r"<\s*([a-zA-Z0-9]+)", tok)
            name = name_match.group(1).lower() if name_match else ""
            stack.append(name)
            result.append(tok)
        else:
            if text_len >= limit:
                continue
            remaining = limit - text_len
            chunk = tok[:remaining]
            text_len += len(chunk)
            result.append(chunk)
            if text_len >= limit:
                result.append("...")
                break
    for name in reversed(stack):
        if name:
            result.append(f"</{name}>")
    global PRINT_COUNTER

    return "".join(result)


def normalize_html_for_qt(
    raw_html: str,
    strip_classes: Optional[Iterable[str]] = None,
    css="",
    font_size=None,
) -> str:
    if not raw_html:
        return ""
    s = raw_html.strip()
    if not s.lstrip().startswith("<"):
        return f"<html><body><span>{_html.escape(s)}</span></body></html>"
    m = re.search(r"(?is)<!--\s*StartFragment\s*-->(.*?)<!--\s*EndFragment\s*-->", s)
    if m:
        s = m.group(1).strip()
    head_styles: list[str] = []
    for match in re.finditer(r"(?is)<\s*style\b[^>]*>(.*?)</\s*style\s*>", s):
        head_styles.append(match.group(1))
    for match in re.finditer(
        r'(?is)<\s*link\b[^>]*rel\s*=\s*"(?:stylesheet|style)"[^>]*href\s*=\s*"([^"]+)"[^>]*>',
        s,
    ):
        href = (match.group(1) or "").strip()
        if href:
            p = Path(href)
            if p.is_file():
                try:
                    head_styles.append(p.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
    s = re.sub(r"(?is)<\s*link\b[^>]*>", "", s)
    s = re.sub(r"(?is)<\s*/?\s*html\b[^>]*>", "", s)
    s = re.sub(r"(?is)<\s*/?\s*body\b[^>]*>", "", s)
    s = re.sub(r"(?is)<\s*head\b[^>]*>.*?</\s*head\s*>", "", s)
    s = re.sub(r"(?is)<\s*br\s*/?\s*>", "<br>", s)
    s = s.replace("&#160;", "&nbsp;")

    def _fix_whitespace_in_style(match: re.Match) -> str:
        style = match.group(1)
        style2 = re.sub(
            r"(?is)(^|;)\s*white-space\s*:\s*pre\s*(;|$)",
            r"\1 white-space: pre-wrap\2",
            style,
        )
        style2 = re.sub(r";{2,}", ";", style2).strip(" ;")
        return f'style="{style2}"' if style2 else ""

    s = re.sub(r'(?is)\bstyle\s*=\s*"([^"]*)"', _fix_whitespace_in_style, s)
    s = re.sub(r"(?is)(<br>\s*){4,}", "<br><br>", s)
    s = re.sub(r"(?is)^\s*(<br>\s*)+", "", s)
    s = re.sub(r"(?is)(<br>\s*)+\s*$", "", s)
    s = re.sub(r'(?is)\s*href\s*=\s*"[^"]*"', "", s)
    s = re.sub(r"(?is)\s*href\s*=\s*'[^']*'", "", s)

    # Strip inline font sizes and font tag sizes

    s = re.sub(r"(?is)font-size\s*:\s*[0-9]*\.?[0-9]+\s*(px|pt|em|rem|%)?\s*;?", "", s)
    s = re.sub(r'(?is)(<\s*font\b[^>]*?)\s*size\s*=\s*"?.*?"?([^>]*>)', r"\1\2", s)
    s = re.sub(r'(?is)\s*style\s*=\s*([\'"])\s*\1', "", s)

    cls_list = [c.strip() for c in (strip_classes or []) if c and str(c).strip()]
    if cls_list:
        for cls in cls_list:
            pattern = rf"(?is)<([a-z0-9]+)([^>]*\bclass\s*=\s*\"[^\"]*\b{re.escape(cls)}\b[^\"]*\"[^>]*)>.*?</\1\s*>"
            s = re.sub(pattern, "", s)
            pattern_single = rf"(?is)<([a-z0-9]+)([^>]*\bclass\s*=\s*\"[^\"]*\b{re.escape(cls)}\b[^\"]*\"[^>]*)\s*/>"
            s = re.sub(pattern_single, "", s)

    # ## remove all button tags
    # s = re.sub(r"(?is)<\s*button\b[^>]*>.*?</\s*button\s*>", "", s)
    # s = re.sub(r"(?is)<\s*button\b[^>]*/\s*>", "", s)

    if not re.search(r"(?is)<\s*(div|p|pre|table|ul|ol|h[1-6]|blockquote)\b", s):
        s = f"<div>{s}</div>"

    def _strip_font_sizes(css: str) -> str:
        css = re.sub(
            r"(?is)font-size\s*:\s*[0-9]*\.?[0-9]+\s*(px|pt|em|rem|%)?\s*;?",
            "",
            css,
        )
        css = re.sub(
            r'(?is)(<\s*font\b[^>]*?)\s*size\s*=\s*"?.*?"?([^>]*>)',
            r"\1\2",
            css,
        )
        css = re.sub(r'(?is)\s*style\s*=\s*([\'"])\s*\1', "", css)
        return css

    cleaned_head_styles = [_strip_font_sizes(h) for h in head_styles]
    style_block = (
        f"<style>{' '.join(cleaned_head_styles)}</style>" if cleaned_head_styles else ""
    )
    # print(f"<html><body>{style_block}{s}</body></html>")
    html = f"<html><body>{style_block}{s}</body></html>"

    css = css or ""
    if css.strip():
        css_block = f"<style>{css}</style>"
        if "<body" in html:
            combined = re.sub(
                r"(?is)<\s*body\b[^>]*>",
                lambda m: m.group(0) + css_block,
                html,
                count=1,
            )
        else:
            combined = css_block + html
    else:
        combined = html

    if font_size is not None:
        combined = re.sub(
            r"(?is)(<\s*body\b[^>]*>)",
            lambda m: f"{m.group(1)}<style>body {{ font-size: {int(font_size)}pt; }}</style>",
            combined,
            count=1,
        )

    return combined
