"""Build only _site; never modify originals or legacy YYYY-MM directories."""
import io
import json
import re
import shutil
import warnings
from pathlib import Path
from urllib.parse import quote, urlsplit

from PIL import Image, ImageCms, ImageOps

MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z")
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
warnings.simplefilter("error", Image.DecompressionBombWarning)


def convert(source, target, size, quality):
    with Image.open(source) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError(f"Animated/multipage image is unsupported: {source}")
        image = ImageOps.exif_transpose(original)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        alpha = image.convert("RGBA").getchannel("A")
        profile = image.info.get("icc_profile")
        if profile:
            # Broken profiles fail the build rather than silently changing colors.
            color = image if image.mode in ("RGB", "CMYK", "LAB") else image.convert("RGB")
            rgb = ImageCms.profileToProfile(
                color, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                ImageCms.createProfile("sRGB"), outputMode="RGB")
        else:
            rgb = image.convert("RGB")
        white = Image.new("RGB", rgb.size, "white")
        white.paste(rgb, mask=alpha)
        # Fresh image ensures EXIF/GPS/comments/ICC are not copied to the JPEG.
        clean = Image.new("RGB", white.size)
        clean.paste(white)
        target.parent.mkdir(parents=True, exist_ok=True)
        clean.save(target, "JPEG", quality=quality, optimize=True, progressive=False)


def build(root):
    root = Path(root).resolve()
    config = json.loads((root / "photo-config.json").read_text(encoding="utf-8"))
    base = config["base_url"].rstrip("/")
    url = urlsplit(base)
    if url.scheme != "https" or not url.netloc or url.query or url.fragment:
        raise ValueError("base_url must be an HTTPS URL without query/fragment")
    size, quality = config["max_size"], config["jpeg_quality"]
    if type(size) is not int or not 1 <= size <= 1920:
        raise ValueError("max_size must be 1..1920")
    if type(quality) is not int or not 1 <= quality <= 95:
        raise ValueError("jpeg_quality must be 1..95")
    key = config.get("json_key", "photos")
    if not isinstance(key, str) or not key:
        raise ValueError("json_key must be a nonempty string")
    months = set(config.get("empty_months", []))
    if any(not isinstance(m, str) or not MONTH.fullmatch(m) for m in months):
        raise ValueError("Invalid empty_months")

    # Explicit source roots only. _site can never become an input.
    roots = [root]
    originals = root / "originals"
    if originals.is_symlink():
        raise ValueError("originals must not be a symlink")
    if originals.exists():
        roots.append(originals)
    planned = {}
    for parent in roots:
        for month_dir in sorted(parent.iterdir()):
            if not MONTH.fullmatch(month_dir.name):
                if parent == originals and not month_dir.name.startswith("."):
                    raise ValueError(f"Expected YYYY-MM directory: {month_dir}")
                continue
            if month_dir.is_symlink() or not month_dir.is_dir():
                raise ValueError(f"Invalid month directory: {month_dir}")
            months.add(month_dir.name)
            for source in sorted(month_dir.rglob("*")):
                if source.is_symlink():
                    raise ValueError(f"Symlink is not allowed: {source}")
                if not source.is_file() or source.name.startswith("."):
                    continue
                if source.suffix.lower() not in EXTENSIONS:
                    if source.name != "photos.json":
                        raise ValueError(f"Unsupported file: {source}")
                    continue
                relative = Path(month_dir.name) / source.relative_to(month_dir).with_suffix(".jpg")
                collision_key = relative.as_posix().casefold()
                if collision_key in planned:
                    raise ValueError(f"JPEG name collision: {source} / {planned[collision_key][0]}")
                planned[collision_key] = (source, relative)

    out = root / "_site"
    if out.is_symlink():
        raise ValueError("_site must not be a symlink")
    # This fixed, dedicated output directory is the only deletion target.
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    lists = {month: [] for month in sorted(months)}
    for source, relative in sorted(planned.values(), key=lambda pair: pair[1].as_posix()):
        convert(source, out / relative, size, quality)
        lists[relative.parts[0]].append(base + "/" + quote(relative.as_posix(), safe="/"))
    for month, photos in lists.items():
        directory = out / month
        directory.mkdir(exist_ok=True)
        (directory / "photos.json").write_text(
            json.dumps({key: photos}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / ".nojekyll").touch()
    # Deliberately publish no repository files or originals.
    (out / "index.html").write_text(
        '<!doctype html><html lang="ja"><meta charset="utf-8">'
        '<title>Blue Museum</title><h1>Blue Museum Memories</h1>'
        '<p>月別の photos.json から写真を取得できます。</p></html>\n', encoding="utf-8")
    print(f"Built {len(planned)} JPEGs in {len(months)} months: {out}")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
