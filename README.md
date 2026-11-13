# csv-to-video

A small Python CLI that turns a product CSV into MP4 slideshow videos.
Each row has an article (SKU) and a list of images separated by `;`.
The script builds one video per row with ffmpeg, saves it to an output folder
and writes the video file name back to the CSV.

![preview](docs/preview.gif)

## Features

- Any number of images per row (local paths or `http(s)` URLs)
- Images are fitted to one frame size without stretching (letterbox)
- Styles: `zoom` (Ken Burns + crossfade, default), `fade`, `slide`, `cut`
- Per-row style and duration via optional `prompt` / `duration` columns
- English and Russian column names are detected automatically
  (`article` / `sku` / `артикул`, `images` / `картинки`), or set them with flags
- CSV delimiter auto-detection, `utf-8-sig` by default (opens fine in Excel)
- The input CSV is not modified unless you pass `--in-place`
- Errors in one row do not stop the others; exit code `2` if any row failed

## Requirements

- Python 3.10+ (standard library only)
- [ffmpeg](https://ffmpeg.org/) and `ffprobe` in `PATH`
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: download a build from https://www.gyan.dev/ffmpeg/builds/ and add `bin` to `PATH`
- Pillow, only for generating the demo images: `pip install -r requirements.txt`

## CSV format

```csv
article,images
SKU-1001,SKU-1001_1.png ; SKU-1001_2.png ; SKU-1001_3.png
SKU-1002,SKU-1002_1.png ; SKU-1002_2.png
```

Relative image paths are looked up in `--images-dir`, then next to the CSV,
then in the current folder.

Output: `videos/SKU-1001.mp4`, `videos/SKU-1002.mp4` and a CSV with a new `video` column.

## Quick start

```bash
pip install -r requirements.txt
python3 make_sample.py            # creates sample/products.csv and sample/images/*.png
python3 csv_to_video.py \
  --csv sample/products.csv \
  --images-dir sample/images \
  --output-dir sample/videos \
  --output-csv sample/videos/products_out.csv
```

Example output:

```
done: SKU-1001 -> SKU-1001.mp4 (3 images, style zoom)
done: SKU-1002 -> SKU-1002.mp4 (2 images, style zoom)
videos built: 2, errors: 0
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--csv` | required | input CSV |
| `--images-dir` | – | base folder for relative image paths |
| `--output-dir` | `./videos` | where to save videos |
| `--output-csv` | `<output-dir>/<name>_out.csv` | CSV with the `video` column |
| `--in-place` | off | write the `video` column into the input CSV |
| `--prompt` / `--style` | `zoom` | `zoom`, `fade`, `slide` or `cut` |
| `--duration` | `3` | seconds per image |
| `--fade` | `0.4` | transition length in seconds, `0` disables it |
| `--width` / `--height` | `1920` / `1080` | frame size |
| `--fps` | `30` | frames per second |
| `--delimiter` | auto | CSV delimiter |
| `--encoding` | `utf-8-sig` | CSV encoding |
| `--article-column` / `--images-column` | auto | column names if not detected |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The end-to-end test generates the sample data, renders small videos into a
temporary folder and checks the output CSV. It is skipped if ffmpeg is not installed.

## How it works

1. Every image is scaled and padded to the target frame, then rendered into a
   short clip (`zoompan` for `zoom` / `slide`).
2. Clips are joined with the `xfade` filter (or the concat demuxer for `cut`).
3. Video is encoded as H.264, `yuv420p`, with `+faststart` for web playback.

## License

MIT
