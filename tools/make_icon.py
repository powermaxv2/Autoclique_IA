"""Génère l'icône d'Autoclique IA (autoclique/assets/icon.png et icon.ico).

Usage : python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "autoclique" / "assets"
SIZE = 1024  # dessin en haute résolution, puis réduction (anticrénelage)


def gradient(size, top, bottom):
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom))
        draw.line([(0, y), (size, y)], fill=color)
    return image


def make_icon() -> Image.Image:
    s = SIZE
    background = gradient(s, (47, 96, 216), (40, 170, 235))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, s - 40, s - 40], radius=220, fill=255)
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    icon.paste(background, (0, 0), mask)
    draw = ImageDraw.Draw(icon)

    # Ondes du clic
    cx, cy = 390, 380
    for radius, width, alpha in ((120, 34, 255), (205, 30, 170), (290, 26, 90)):
        draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=180, end=270,
                 fill=(255, 255, 255, alpha), width=width)
        draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=290, end=340,
                 fill=(255, 255, 255, alpha), width=width)
        draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=110, end=160,
                 fill=(255, 255, 255, alpha), width=width)

    # Curseur (flèche) avec ombre
    arrow = [(0, 0), (0, 470), (120, 360), (205, 560), (290, 522), (205, 330), (360, 330)]
    ox, oy = cx - 10, cy - 10
    points = [(ox + x, oy + y) for x, y in arrow]
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 18, y + 22) for x, y in points], fill=(10, 30, 80, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    icon = Image.alpha_composite(icon, shadow)
    draw = ImageDraw.Draw(icon)
    draw.polygon(points, fill=(255, 255, 255, 255))
    draw.line(points + [points[0]], fill=(25, 45, 110, 255), width=22, joint="curve")
    return icon


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = make_icon()
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png", optimize=True)
    icon.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Icône générée dans", ASSETS)


if __name__ == "__main__":
    main()
