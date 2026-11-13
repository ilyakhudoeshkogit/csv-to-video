#!/usr/bin/env python3
"""Build MP4 slideshow videos from images listed in a CSV file.

Expected input:
  - a column with an article / SKU;
  - a column with image paths (or URLs) separated by semicolons ";"
    (usually 3, but any number works);
  - each video is saved to a separate output folder;
  - the video file name is written back to the CSV (new "video" column).

Rendering is done with ffmpeg: images are fitted to one frame size and
joined with a transition (default: gentle zoom + crossfade).
A "prompt" / "style" column or the --prompt flag selects the style:
zoom, fade, slide, cut.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# Column names are matched in English and Russian, so CSV exports
# from local marketplaces work without renaming the headers.
ARTICLE_ALIASES = {
    "артикул", "article", "sku", "id", "код", "articul", "артикул товара",
}
IMAGES_ALIASES = {
    "картинки", "картинка", "изображения", "изображение", "images", "image",
    "photos", "photo", "файлы", "файл", "pictures", "pics",
}
PROMPT_ALIASES = {"промт", "промпт", "prompt", "style", "стиль"}
DURATION_ALIASES = {"duration", "длительность", "секунды", "sec", "seconds"}
VIDEO_COLUMN = "video"

STYLES = ("zoom", "fade", "slide", "cut")


class RowError(Exception):
    pass


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def normalize_header(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def find_column(headers: list[str], aliases: set[str]) -> str | None:
    normalized = {h: normalize_header(h) for h in headers}
    for original, norm in normalized.items():
        if norm in aliases:
            return original
    # partial match if there is no exact one
    for original, norm in normalized.items():
        for alias in aliases:
            if alias and alias in norm:
                return original
    return None


def split_images(cell: str) -> list[str]:
    text = (cell or "").strip()
    if not text:
        return []
    # main separator is ";", newline works as a fallback
    parts = re.split(r"\s*;\s*|\n+", text)
    return [p.strip().strip('"').strip("'") for p in parts if p.strip()]


def safe_stem(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"[\\/]+", "_", value)
    value = re.sub(r"[^\w\-.]+", "_", value, flags=re.UNICODE)
    value = value.strip("._") or "video"
    return value[:80]


def run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = "\n".join(tail[-12:])
        raise RuntimeError(f"ffmpeg exited with code {proc.returncode}:\n{hint}")


def resolve_image(
    raw: str,
    images_dir: Path | None,
    csv_dir: Path,
    work_dir: Path,
    index: int,
) -> Path:
    raw = raw.strip()
    if not raw:
        raise RowError("empty image path")

    if re.match(r"^https?://", raw, re.I):
        dest = work_dir / f"dl_{index}{Path(raw.split('?', 1)[0]).suffix or '.jpg'}"
        try:
            urllib.request.urlretrieve(raw, dest)
        except Exception as exc:  # noqa: BLE001
            raise RowError(f"cannot download {raw}: {exc}") from exc
        if not dest.exists() or dest.stat().st_size == 0:
            raise RowError(f"empty download: {raw}")
        return dest

    path = Path(raw).expanduser()
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        if images_dir:
            candidates.append(images_dir / path)
        candidates.append(csv_dir / path)
        candidates.append(Path.cwd() / path)

    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    tried = ", ".join(str(c) for c in candidates)
    raise RowError(f"file not found: {raw} (looked in: {tried})")


def style_filter(style: str, duration: float, fps: int, width: int, height: int) -> str:
    frames = max(int(round(duration * fps)), 1)
    # the image is already fitted to width x height
    if style == "zoom":
        # slow zoom to the center (Ken Burns)
        return (
            f"zoompan=z='min(zoom+0.0008,1.15)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )
    if style == "slide":
        # gentle pan from left to right
        return (
            f"zoompan=z=1.08:d={frames}:"
            f"x='(iw-iw/zoom)*on/{frames}':y='(ih-ih/zoom)/2':"
            f"s={width}x{height}:fps={fps}"
        )
    # fade / cut: just hold the frame for the given time
    return f"fps={fps},trim=duration={duration},setpts=PTS-STARTPTS"


def prepare_clip(
    src: Path,
    dest: Path,
    duration: float,
    fps: int,
    width: int,
    height: int,
    style: str,
) -> None:
    vf_fit = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        + style_filter(style, duration, fps, width, height)
    )
    run_ffmpeg(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-i", str(src),
            "-vf", vf_fit,
            "-t", f"{duration:.3f}",
            "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            str(dest),
        ]
    )


def concat_clips(
    clips: list[Path],
    dest: Path,
    style: str,
    fade: float,
    width: int,
    height: int,
    fps: int,
) -> None:
    if len(clips) == 1 or style == "cut" or fade <= 0:
        lst = dest.with_suffix(".txt")
        lst.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
        try:
            run_ffmpeg(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                    "-movflags", "+faststart",
                    str(dest),
                ]
            )
        finally:
            lst.unlink(missing_ok=True)
        return

    # crossfade between neighbouring clips
    inputs: list[str] = []
    for clip in clips:
        inputs.extend(["-i", str(clip)])

    filters = []
    current = "0:v"
    # take the real duration from the file
    durations = [probe_duration(c) for c in clips]
    offset = 0.0
    for i in range(1, len(clips)):
        overlap = min(fade, durations[i - 1] / 2, durations[i] / 2)
        if overlap < 0.05:
            overlap = 0.05
        offset += durations[i - 1] - overlap
        out = f"xf{i}"
        trans = "slideleft" if style == "slide" else "fade"
        filters.append(
            f"[{current}][{i}:v]xfade=transition={trans}:duration={overlap:.3f}:"
            f"offset={offset:.3f}[{out}]"
        )
        current = out

    run_ffmpeg(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", f"[{current}]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-movflags", "+faststart",
            str(dest),
        ]
    )


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def make_video(
    images: list[Path],
    dest: Path,
    duration: float,
    fps: int,
    width: int,
    height: int,
    style: str,
    fade: float,
    work_dir: Path,
) -> None:
    clips = []
    for i, img in enumerate(images, start=1):
        clip = work_dir / f"clip_{i:02d}.mp4"
        prepare_clip(img, clip, duration, fps, width, height, style)
        clips.append(clip)
    concat_clips(clips, dest, style, fade, width, height, fps)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(f"video was not created: {dest}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build MP4 videos from images listed in a CSV (article + images separated by ';').",
    )
    p.add_argument("--csv", required=True, type=Path, help="input CSV")
    p.add_argument(
        "--images-dir",
        type=Path,
        default=None,
        help="folder used to resolve relative image paths",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("videos"),
        help="where to save videos (default ./videos)",
    )
    p.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="where to save the CSV with the video column (default: next to the videos)",
    )
    p.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the input CSV (by default it is left untouched)",
    )
    p.add_argument("--duration", type=float, default=3.0, help="seconds per image (default 3)")
    p.add_argument("--fps", type=int, default=30, help="frames per second (default 30)")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument(
        "--prompt",
        "--style",
        dest="prompt",
        default="zoom",
        help="video style: zoom, fade, slide, cut (can also be set per row in a prompt column)",
    )
    p.add_argument("--fade", type=float, default=0.4, help="transition length in seconds (0 = no transition)")
    p.add_argument("--encoding", default="utf-8-sig", help="CSV encoding")
    p.add_argument("--delimiter", default=None, help="CSV delimiter (default: auto-detect)")
    p.add_argument(
        "--article-column",
        default=None,
        help="article column name if it is not detected automatically",
    )
    p.add_argument(
        "--images-column",
        default=None,
        help="images column name if it is not detected automatically",
    )
    return p.parse_args(argv)


def detect_delimiter(sample: str, forced: str | None) -> str:
    if forced:
        return forced
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return "," if sample.count(",") >= sample.count(";") else ";"


def load_table(path: Path, encoding: str, delimiter: str | None) -> tuple[list[str], list[dict[str, str]], str]:
    raw = path.read_bytes()
    text = raw.decode(encoding)
    # strip BOM if utf-8-sig did not
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    delim = detect_delimiter(text[:4096], delimiter)
    reader = csv.DictReader(text.splitlines(), delimiter=delim)
    if not reader.fieldnames:
        raise RuntimeError("the CSV has no header row")
    headers = [h if h is not None else "" for h in reader.fieldnames]
    rows = [{k: (v or "") for k, v in row.items() if k is not None} for row in reader]
    return headers, rows, delim


def choose_style(row_prompt: str, default: str) -> str:
    value = normalize_header(row_prompt or default)
    if value in STYLES:
        return value
    # free text: look for a known word
    for style in STYLES:
        if style in value:
            return style
    if any(w in value for w in ("zoom", "ken burns", "зум", "приближ")):
        return "zoom"
    if any(w in value for w in ("slide", "pan", "слайд", "сдвиг")):
        return "slide"
    if any(w in value for w in ("cut", "no transition", "без перехода", "резк")):
        return "cut"
    return default if default in STYLES else "zoom"


def process(args: argparse.Namespace) -> int:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        die("ffmpeg (and ffprobe) must be in PATH. See https://ffmpeg.org/")

    csv_path = args.csv.expanduser().resolve()
    if not csv_path.is_file():
        die(f"file not found: {csv_path}")

    headers, rows, delim = load_table(csv_path, args.encoding, args.delimiter)
    article_col = args.article_column or find_column(headers, ARTICLE_ALIASES)
    images_col = args.images_column or find_column(headers, IMAGES_ALIASES)
    prompt_col = find_column(headers, PROMPT_ALIASES)
    duration_col = find_column(headers, DURATION_ALIASES)

    if not article_col:
        die(
            "article column not found. Pass --article-column NAME. "
            f"Available columns: {', '.join(headers)}"
        )
    if not images_col:
        die(
            "images column not found. Pass --images-column NAME. "
            f"Available columns: {', '.join(headers)}"
        )

    if VIDEO_COLUMN not in headers:
        headers = list(headers) + [VIDEO_COLUMN]

    out_dir = args.output_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = args.images_dir.expanduser().resolve() if args.images_dir else None
    csv_dir = csv_path.parent

    ok = 0
    failed = 0
    used_names: set[str] = set()

    for idx, row in enumerate(rows, start=2):  # 2 = first data row
        article = (row.get(article_col) or "").strip()
        image_cell = row.get(images_col) or ""
        names = split_images(image_cell)
        if not article:
            print(f"row {idx}: empty article, skipped")
            failed += 1
            continue
        if not names:
            print(f"row {idx} ({article}): no images, skipped")
            failed += 1
            continue

        style = choose_style(row.get(prompt_col, "") if prompt_col else "", args.prompt)
        try:
            duration = float(row.get(duration_col) or args.duration) if duration_col else args.duration
        except ValueError:
            duration = args.duration
        if duration <= 0:
            duration = args.duration

        stem = safe_stem(article)
        if stem in used_names:
            stem = f"{stem}_{idx}"
        used_names.add(stem)
        dest = out_dir / f"{stem}.mp4"

        try:
            with tempfile.TemporaryDirectory(prefix="csvvid_") as tmp:
                tmp_path = Path(tmp)
                resolved = [
                    resolve_image(name, images_dir, csv_dir, tmp_path, i)
                    for i, name in enumerate(names, start=1)
                ]
                make_video(
                    resolved,
                    dest,
                    duration=duration,
                    fps=args.fps,
                    width=args.width,
                    height=args.height,
                    style=style,
                    fade=args.fade,
                    work_dir=tmp_path,
                )
        except (RowError, RuntimeError) as exc:
            print(f"row {idx} ({article}): {exc}")
            failed += 1
            row[VIDEO_COLUMN] = ""
            continue

        row[VIDEO_COLUMN] = dest.name
        print(f"done: {article} -> {dest.name} ({len(resolved)} images, style {style})")
        ok += 1

    if args.in_place:
        out_csv = csv_path
    else:
        out_csv = args.output_csv.expanduser().resolve() if args.output_csv else out_dir / f"{csv_path.stem}_out.csv"

    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, delimiter=delim, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"videos built: {ok}, errors: {failed}")
    print(f"CSV with file names: {out_csv}")
    return 0 if failed == 0 else 2


def main() -> None:
    args = parse_args()
    try:
        sys.exit(process(args))
    except RuntimeError as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
