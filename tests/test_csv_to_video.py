import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import csv_to_video as cv  # noqa: E402


class HelpersTest(unittest.TestCase):
    def test_split_images(self):
        self.assertEqual(cv.split_images("a.png ; b.png;c.png"), ["a.png", "b.png", "c.png"])
        self.assertEqual(cv.split_images(""), [])

    def test_find_column_en_and_ru(self):
        self.assertEqual(cv.find_column(["SKU", "Images"], cv.ARTICLE_ALIASES), "SKU")
        self.assertEqual(cv.find_column(["Артикул", "Картинки"], cv.IMAGES_ALIASES), "Картинки")

    def test_safe_stem(self):
        self.assertEqual(cv.safe_stem("a/b c"), "a_b_c")
        self.assertEqual(cv.safe_stem(""), "video")

    def test_choose_style(self):
        self.assertEqual(cv.choose_style("fade please", "zoom"), "fade")
        self.assertEqual(cv.choose_style("", "cut"), "cut")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class EndToEndTest(unittest.TestCase):
    def test_sample_run(self):
        subprocess.run([sys.executable, str(ROOT / "make_sample.py")], check=True, cwd=ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            out_csv = out / "products_out.csv"
            proc = subprocess.run(
                [
                    sys.executable, str(ROOT / "csv_to_video.py"),
                    "--csv", str(ROOT / "sample" / "products.csv"),
                    "--images-dir", str(ROOT / "sample" / "images"),
                    "--output-dir", str(out),
                    "--output-csv", str(out_csv),
                    "--width", "640", "--height", "360", "--duration", "1",
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            for sku in ("SKU-1001", "SKU-1002"):
                self.assertTrue((out / f"{sku}.mp4").stat().st_size > 0)
            with out_csv.open(encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([r["video"] for r in rows], ["SKU-1001.mp4", "SKU-1002.mp4"])


if __name__ == "__main__":
    unittest.main()
