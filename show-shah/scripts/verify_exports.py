import json
from pathlib import Path
from zipfile import ZipFile

metadata = json.loads(Path(".build/video-info.json").read_text())
video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
assert (video["width"], video["height"]) == (1920, 1080)
assert video["codec_name"] == "h264"
assert video["pix_fmt"] in {"yuv420p", "yuvj420p"}
assert video["r_frame_rate"] == "30/1"
assert int(video["nb_frames"]) == 4320
assert abs(float(metadata["format"]["duration"]) - 144) < 0.1
for path in ["exports/show-shah.pptx", "dist/show-shah.pptx"]:
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        slides = [
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        ]
        notes = [
            name
            for name in archive.namelist()
            if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")
        ]
        assert len(slides) == len(notes) == 12
        assert all(b"https://github.com/Manas-thakur/f1/blob/" in archive.read(name) for name in notes)
print("Verified full 144-second HD movie and both 12-slide PowerPoint exports.")
