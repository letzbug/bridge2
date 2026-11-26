"""Generates packaging/EmergenceLab.ico (the three-node EMERGENCE LAB mark – an original design)."""

from pathlib import Path

from PIL import Image, ImageDraw

BG, TEAL, NODE_FILL = (17, 23, 28, 255), (63, 207, 178, 255), (12, 17, 21, 255)


def render(size: int) -> Image.Image:
    s = size * 4                                   # supersample, then downscale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.2), fill=BG)
    top, left, right = (s * .5, s * .24), (s * .23, s * .74), (s * .77, s * .74)
    w = max(4, int(s * 0.055))
    for a, b in ((top, left), (top, right), (left, right)):
        d.line((a, b), fill=TEAL, width=w)
    r = s * 0.11
    for (x, y) in (top, left, right):
        d.ellipse((x - r, y - r, x + r, y + r), fill=NODE_FILL, outline=TEAL, width=w)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).with_name("EmergenceLab.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = render(256)
    base.save(out, format="ICO", sizes=[(n, n) for n in sizes])
    render(512).save(Path(__file__).with_name("EmergenceLab.png"))
    print(f"written {out}")


if __name__ == "__main__":
    main()
