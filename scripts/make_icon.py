"""生成应用图标。

用纯标准库手写 PNG，不引入图像处理依赖。

为什么不用现成的图标文件：图标是二进制黑盒，改了没人知道怎么改回来。
用脚本生成则「改一行代码就能调色」，也方便换配色时重新出一套。

    uv run python scripts/make_icon.py

产物：
    desktop/resources/icon.png     512×512，托盘与打包共用
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "desktop" / "resources" / "icon.png"

SIZE = 512

# 配色与前端 styles.css 的 CSS 变量保持一致
BG_TOP = (26, 29, 36)
BG_BOTTOM = (18, 20, 26)
ACCENT_START = (91, 157, 255)
ACCENT_END = (78, 201, 160)
PAGE = (230, 232, 236)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def sd_rounded_box(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    """圆角矩形的有符号距离场。"""
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def sd_circle(px: float, py: float, cx: float, cy: float, r: float) -> float:
    """圆的有符号距离场。"""
    return math.hypot(px - cx, py - cy) - r


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = clamp(t)
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def over(
    base: tuple[int, int, int], layer: tuple[int, int, int], alpha: float
) -> tuple[int, int, int]:
    """把 layer 以 alpha 叠加到 base 上。"""
    return (
        int(base[0] + (layer[0] - base[0]) * alpha),
        int(base[1] + (layer[1] - base[1]) * alpha),
        int(base[2] + (layer[2] - base[2]) * alpha),
    )


def render() -> list[list[tuple[int, int, int, int]]]:
    """逐像素渲染图标。

    用有符号距离场做抗锯齿：每个像素只算一次距离，
    比超采样快得多，边缘质量也一样。
    """
    rows: list[list[tuple[int, int, int, int]]] = []
    center = SIZE / 2

    for y in range(SIZE):
        row: list[tuple[int, int, int, int]] = []
        for x in range(SIZE):
            px, py = x + 0.5, y + 0.5

            # 背景：圆角方形
            bg_d = sd_rounded_box(px, py, center, center, center - 8, center - 8, 112)
            bg_alpha = clamp(0.5 - bg_d)
            if bg_alpha <= 0:
                row.append((0, 0, 0, 0))
                continue

            # 背景垂直渐变
            color = mix(BG_TOP, BG_BOTTOM, py / SIZE)

            # 墨滴：一个圆，沿对角线做蓝→青渐变
            drop_d = sd_circle(px, py, center, center, 150)
            drop_alpha = clamp(0.5 - drop_d)
            if drop_alpha > 0:
                t = clamp(((px - center) + (py - center)) / (SIZE * 0.9) + 0.5)
                color = over(color, mix(ACCENT_START, ACCENT_END, t), drop_alpha)

                # 圆内挖出三行「文字」：宽度递减，像一段落
                for width, offset in ((74, -40), (74, 0), (42, 40)):
                    line_d = sd_rounded_box(px, py, center, center + offset, width, 10, 10)
                    line_alpha = clamp(0.5 - line_d) * drop_alpha
                    if line_alpha > 0:
                        color = over(color, BG_BOTTOM, line_alpha)

            row.append((color[0], color[1], color[2], int(bg_alpha * 255)))
        rows.append(row)

    return rows


def write_png(path: Path, rows: list[list[tuple[int, int, int, int]]]) -> None:
    """写出 RGBA PNG。"""
    height = len(rows)
    width = len(rows[0])

    raw = bytearray()
    for row in rows:
        raw.append(0)  # 每行的过滤器类型：0 = None
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(png))


def main() -> int:
    rows = render()
    write_png(OUTPUT, rows)
    print(f"已生成 {OUTPUT.relative_to(ROOT)}（{SIZE}×{SIZE}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
