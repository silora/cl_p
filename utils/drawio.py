"""Convert draw.io/diagrams.net payloads (URL or compressed text) into .drawio or PNG files."""

import base64
import subprocess
import tempfile
import urllib.parse
import zlib
from pathlib import Path

from config import get_tools_settings

TOOLS_CFG = get_tools_settings()
DEFAULT_DRAWIO_BIN = Path(
    TOOLS_CFG.get("drawioExe") or r"C:\Program Files\draw.io\draw.io.exe"
)


def _add_padding(data: str) -> str:
    """Pad base64 string to a multiple of 4 characters."""
    missing = (-len(data)) % 4
    if missing:
        data += "=" * missing
    return data


def _extract_payload(raw: str) -> str:
    """Return the compressed payload from a URL or raw string."""
    txt = raw.strip()
    if "://" in txt:
        parsed = urllib.parse.urlparse(txt)
        candidate = (
            parsed.fragment or urllib.parse.parse_qs(parsed.query).get("data", [""])[0]
        )
        if not candidate:
            raise ValueError(
                "No draw.io payload found in URL (expected fragment or ?data=)"
            )
        txt = candidate
    txt = urllib.parse.unquote(txt)
    if txt.startswith("#"):
        txt = txt[1:]
    return txt


def decode_drawio(raw: str) -> str:
    """Decode a draw.io compressed string to XML."""
    payload = _extract_payload(raw).strip()

    # Already XML (e.g., URL-encoded XML from copy)?
    if payload.startswith("<"):
        return payload

    b64 = _add_padding(payload.replace("-", "+").replace("_", "/"))
    try:
        blob = base64.b64decode(b64)
    except Exception as exc:  # binascii.Error
        raise ValueError("Payload is not valid base64 or XML") from exc

    try:
        xml_bytes = zlib.decompress(blob, -15)  # raw DEFLATE
    except zlib.error:
        try:
            xml_bytes = zlib.decompress(blob)  # fallback if zlib header present
        except Exception as exc:
            raise ValueError("Unable to decompress draw.io payload") from exc
    return xml_bytes.decode("utf-8", errors="replace")


def url_to_png(
    payload: str,
    output_png: str,
    drawio_bin: Path | str | None = None,
    keep_drawio: str | Path | None = None,
) -> Path:
    """
    Convert a draw.io URL/payload directly to a PNG by shelling out to draw.io.

    Args:
        payload: Full draw.io URL or compressed payload string.
        output_png: Destination PNG path.
        drawio_bin: Optional path to draw.io executable. Defaults to the standard Windows location.
        keep_drawio: Optional path to also save the intermediate .drawio file.
    """
    drawio_exe = Path(drawio_bin) if drawio_bin else DEFAULT_DRAWIO_BIN
    if not drawio_exe.exists():
        raise FileNotFoundError(
            f"draw.io executable not found at {drawio_exe}. "
            "Pass --drawio-bin or set drawio_bin."
        )

    png_path = Path(output_png).resolve()
    png_path.parent.mkdir(parents=True, exist_ok=True)

    xml = decode_drawio(payload)

    temp_file: Path | None = None
    diagram_path: Path
    try:
        if keep_drawio:
            diagram_path = Path(keep_drawio).resolve()
            diagram_path.parent.mkdir(parents=True, exist_ok=True)
            diagram_path.write_text(xml, encoding="utf-8")
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".drawio")
            tmp.write(xml.encode("utf-8"))
            tmp.flush()
            tmp.close()
            temp_file = Path(tmp.name)
            diagram_path = temp_file

        cmd = [
            str(drawio_exe),
            "--export",
            str(diagram_path),
            "--format",
            "png",
            "--output",
            str(png_path),
            "-t",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"draw.io export failed ({result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        return png_path
    finally:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass


# def url_to_svg(
#     payload: str,
#     output_svg: str,
#     drawio_bin: Path | str | None = None,
#     keep_drawio: str | Path | None = None,
# ) -> Path:
#     """
#     Convert a draw.io URL/payload directly to an SVG by shelling out to draw.io.
#     """
#     drawio_exe = Path(drawio_bin) if drawio_bin else DEFAULT_DRAWIO_BIN
#     if not drawio_exe.exists():
#         raise FileNotFoundError(
#             f"draw.io executable not found at {drawio_exe}. "
#             "Pass --drawio-bin or set drawio_bin."
#         )

#     svg_path = Path(output_svg).resolve()
#     svg_path.parent.mkdir(parents=True, exist_ok=True)

#     xml = decode_drawio(payload)

#     temp_file: Path | None = None
#     diagram_path: Path
#     try:
#         if keep_drawio:
#             diagram_path = Path(keep_drawio).resolve()
#             diagram_path.parent.mkdir(parents=True, exist_ok=True)
#             diagram_path.write_text(xml, encoding="utf-8")
#         else:
#             tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".drawio")
#             tmp.write(xml.encode("utf-8"))
#             tmp.flush()
#             tmp.close()
#             temp_file = Path(tmp.name)
#             diagram_path = temp_file

#         cmd = [
#             str(drawio_exe),
#             "--export",
#             str(diagram_path),
#             "--format",
#             "svg",
#             "--output",
#             str(svg_path),
#         ]
#         result = subprocess.run(
#             cmd,
#             capture_output=True,
#             text=True,
#             encoding="utf-8",
#             errors="replace",
#         )
#         if result.returncode != 0:
#             raise RuntimeError(
#                 f"draw.io export failed ({result.returncode}): "
#                 f"{result.stderr or result.stdout}"
#             )
#         return svg_path
#     finally:
#         if temp_file and temp_file.exists():
#             try:
#                 temp_file.unlink()
#             except Exception:
#                 pass


def url_to_svg(
    payload: str,
    output_svg: str,
    drawio_bin: Path | str | None = None,
    keep_drawio: str | Path | None = None,
) -> Path:
    """
    Convert a draw.io URL/payload directly to a PNG by shelling out to draw.io.

    Args:
        payload: Full draw.io URL or compressed payload string.
        output_svg: Destination SVG path.
        drawio_bin: Optional path to draw.io executable. Defaults to the standard Windows location.
        keep_drawio: Optional path to also save the intermediate .drawio file.
    """
    drawio_exe = Path(drawio_bin) if drawio_bin else DEFAULT_DRAWIO_BIN
    if not drawio_exe.exists():
        raise FileNotFoundError(
            f"draw.io executable not found at {drawio_exe}. "
            "Pass --drawio-bin or set drawio_bin."
        )

    svg_path = Path(output_svg).resolve()
    svg_path.parent.mkdir(parents=True, exist_ok=True)

    xml = decode_drawio(payload)

    temp_file: Path | None = None
    diagram_path: Path
    try:
        if keep_drawio:
            diagram_path = Path(keep_drawio).resolve()
            diagram_path.parent.mkdir(parents=True, exist_ok=True)
            diagram_path.write_text(xml, encoding="utf-8")
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".drawio")
            tmp.write(xml.encode("utf-8"))
            tmp.flush()
            tmp.close()
            temp_file = Path(tmp.name)
            diagram_path = temp_file

        cmd = [
            str(drawio_exe),
            "--export",
            str(diagram_path),
            "--format",
            "svg",
            "--output",
            str(svg_path),
            "-t",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"draw.io export failed ({result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        return svg_path
    finally:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass


def placeholder_drawio_svg(xml: str) -> bytes:
    """Generate a simple placeholder SVG when draw.io export is unavailable."""
    snippet = (xml or "").strip().replace("\n", " ")
    if len(snippet) > 160:
        snippet = snippet[:157] + "..."
    snippet = snippet.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    width, height = 420, 260
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#1f2428" rx="14" ry="14"/>
<text x="20" y="40" fill="#c9d1d9" font-family="Consolas, Menlo, monospace" font-size="18" font-weight="700">DRAW.IO</text>
<text x="20" y="72" fill="#8b949e" font-family="Consolas, Menlo, monospace" font-size="14">
<tspan>Preview unavailable (CLI missing)</tspan>
</text>
<text x="20" y="110" fill="#8b949e" font-family="Consolas, Menlo, monospace" font-size="12">
<tspan>Content:</tspan>
</text>
<text x="20" y="134" fill="#8b949e" font-family="Consolas, Menlo, monospace" font-size="11">
{snippet}
</text>
</svg>"""
    return body.encode("utf-8")


def is_drawio_payload(text: str) -> bool:
    payload = (text or "").strip()
    if not payload:
        return False
    if "%3CmxGraphModel" in payload or "<mxGraphModel" in payload:
        return True
    # try:
    #     drawio.decode_drawio(payload)
    #     return True
    # except Exception:
    #     return False


if __name__ == "__main__":
    example_url = "%3CmxGraphModel%3E%3Croot%3E%3CmxCell%20id%3D%220%22%2F%3E%3CmxCell%20id%3D%221%22%20parent%3D%220%22%2F%3E%3CmxCell%20id%3D%222%22%20value%3D%22%22%20style%3D%22verticalLabelPosition%3Dbottom%3BverticalAlign%3Dtop%3Bhtml%3D1%3Bshape%3Dmxgraph.basic.drop%3Brounded%3D1%3Bshadow%3D1%3BstrokeColor%3D%23CCA6A8%3BstrokeWidth%3D7%3BfontFamily%3DFira%20Code%3BfontSize%3D18%3BfontColor%3D%23333333%3BfillColor%3D%23FFCFD2%3Brotation%3D102.5%3BgradientColor%3D%23DBCDF0%3B%22%20vertex%3D%221%22%20parent%3D%221%22%3E%3CmxGeometry%20x%3D%22251.9991655500988%22%20y%3D%22585.9998594013205%22%20width%3D%2284%22%20height%3D%22120%22%20as%3D%22geometry%22%2F%3E%3C%2FmxCell%3E%3CmxCell%20id%3D%223%22%20value%3D%22%22%20style%3D%22verticalLabelPosition%3Dbottom%3BverticalAlign%3Dtop%3Bhtml%3D1%3Bshape%3Dmxgraph.basic.drop%3Brounded%3D1%3Bshadow%3D1%3BstrokeColor%3D%23CCA6A8%3BstrokeWidth%3D7%3BfontFamily%3DFira%20Code%3BfontSize%3D18%3BfontColor%3D%23333333%3BfillColor%3D%23FFCFD2%3Brotation%3D167.5%3BflipH%3D0%3BflipV%3D0%3BgradientColor%3D%23F2C6DE%3B%22%20vertex%3D%221%22%20parent%3D%221%22%3E%3CmxGeometry%20x%3D%22304.99916555009884%22%20y%3D%22532.9998594013205%22%20width%3D%2284%22%20height%3D%22120%22%20as%3D%22geometry%22%2F%3E%3C%2FmxCell%3E%3CmxCell%20id%3D%224%22%20value%3D%22%22%20style%3D%22verticalLabelPosition%3Dbottom%3BverticalAlign%3Dtop%3Bhtml%3D1%3Bshape%3Dmxgraph.basic.half_circle%3Brounded%3D1%3Bshadow%3D1%3BstrokeWidth%3D7%3BfontFamily%3DFira%20Code%3BfontSize%3D18%3BfontColor%3D%23333333%3Brotation%3D75%3BfillColor%3D%23E2E2DF%3BstrokeColor%3D%23B5B5B2%3BgradientColor%3D%23C7C7C7%3B%22%20vertex%3D%221%22%20parent%3D%221%22%3E%3CmxGeometry%20x%3D%22318.99916555009884%22%20y%3D%22685.9998594013205%22%20width%3D%2263.4398314506459%22%20height%3D%2231.719708063955082%22%20as%3D%22geometry%22%2F%3E%3C%2FmxCell%3E%3CmxCell%20id%3D%225%22%20value%3D%22%22%20style%3D%22verticalLabelPosition%3Dbottom%3BverticalAlign%3Dtop%3Bhtml%3D1%3Bshape%3Dmxgraph.basic.half_circle%3Brounded%3D1%3Bshadow%3D1%3BstrokeColor%3D%23A8A8A6%3BstrokeWidth%3D7%3BfontFamily%3DFira%20Code%3BfontSize%3D18%3BfontColor%3D%23333333%3BfillColor%3D%23D2D2CF%3Brotation%3D-165%3B%22%20vertex%3D%221%22%20parent%3D%221%22%3E%3CmxGeometry%20x%3D%22370.99916555009884%22%20y%3D%22633.9998594013205%22%20width%3D%2263.4398314506459%22%20height%3D%2231.719708063955082%22%20as%3D%22geometry%22%2F%3E%3C%2FmxCell%3E%3C%2Froot%3E%3C%2FmxGraphModel%3E"

    output = "output.svg"
    url_to_svg(example_url, output)
    print(f"Saved SVG to {output}")
