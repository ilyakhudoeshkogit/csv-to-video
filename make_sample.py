#!/usr/bin/env python3
"""Create a demo CSV and a few coloured placeholder images.

All sample data is made up: two fake products with generated pictures.
"""

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "sample" / "images"
CSV_PATH = ROOT / "sample" / "products.csv"

# The first product has 3 images, the second has 2:
# the script does not require exactly three.
ITEMS = [
    {"article": "SKU-1001", "colors": [("#1d4ed8", "Blue"), ("#047857", "Green"), ("#b45309", "Orange")]},
    {"article": "SKU-1002", "colors": [("#6d28d9", "Purple"), ("#be123c", "Red")]},
]


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_image(path: Path, color: str, title: str, subtitle: str) -> None:
    img = Image.new("RGB", (1600, 900), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 700, 1600, 900), fill="#111111")
    draw.text((80, 740), title, font=load_font(72), fill="white")
    draw.text((80, 830), subtitle, font=load_font(36), fill="#dddddd")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in ITEMS:
        names = []
        for i, (color, label) in enumerate(item["colors"], start=1):
            fname = f"{item['article']}_{i}.png"
            make_image(IMG_DIR / fname, color, item["article"], f"{label} frame {i}")
            names.append(fname)
        rows.append({"article": item["article"], "images": " ; ".join(names)})

    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["article", "images"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"images: {IMG_DIR.relative_to(ROOT)}")
    print(f"csv:    {CSV_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
