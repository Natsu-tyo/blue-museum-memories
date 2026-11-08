import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

spec = importlib.util.spec_from_file_location("builder", Path(__file__).resolve().parents[1] / "scripts/build_photos.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "photo-config.json").write_text(json.dumps({
            "base_url": "https://natsu-tyo.github.io/blue-museum-memories",
            "max_size": 1920, "jpeg_quality": 85, "empty_months": ["2026-12"]}), encoding="utf-8")

    def image(self, name, mode="RGB", size=(3840, 2160)):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new(mode, size).save(path)
        return path

    def test_legacy_new_metadata_alpha_and_rebuild(self):
        source = self.image("2026-10/test.jpg")
        original = source.read_bytes()
        (source.parent / "photos.json").write_text('{"old": true}')
        self.image("originals/2026-11/日本 語.png", "RGBA", (100, 200))
        builder.build(self.root)
        out = self.root / "_site"
        with Image.open(out / "2026-10/test.jpg") as im:
            self.assertEqual(im.size, (1920, 1080))
            self.assertFalse(im.getexif())
        with Image.open(out / "2026-11/日本 語.jpg") as im:
            self.assertEqual(im.size, (100, 200))
            self.assertEqual(im.getpixel((0, 0)), (255, 255, 255))
        self.assertIn("%E6%97%A5", (out / "2026-11/photos.json").read_text())
        self.assertEqual(json.loads((out / "2026-12/photos.json").read_text()), {"photos": []})
        self.assertFalse((out / "originals").exists())
        before = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        builder.build(self.root)
        self.assertEqual(before, {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()})
        self.assertEqual(source.read_bytes(), original)
        source.unlink()
        builder.build(self.root)
        self.assertFalse((out / "2026-10/test.jpg").exists())

    def test_collision_fails(self):
        self.image("2026-10/a.png")
        self.image("originals/2026-10/a.jpg")
        with self.assertRaisesRegex(ValueError, "collision"):
            builder.build(self.root)

    def test_corrupt_fails(self):
        path = self.root / "originals/2026-10/broken.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not an image")
        with self.assertRaises(Exception):
            builder.build(self.root)

    def test_exif_orientation_and_gps_removed(self):
        path = self.root / "2026-10/rotated.jpg"
        path.parent.mkdir()
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "private description"
        Image.new("RGB", (300, 100)).save(path, exif=exif)
        builder.build(self.root)
        with Image.open(self.root / "_site/2026-10/rotated.jpg") as im:
            self.assertEqual(im.size, (100, 300))
            self.assertFalse(im.getexif())


if __name__ == "__main__":
    unittest.main()
