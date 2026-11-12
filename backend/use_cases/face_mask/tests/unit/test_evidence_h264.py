import json
import shutil
import subprocess

import numpy as np
import pytest

from app.core.config import EvidenceConfig
from app.services.evidence_service import EvidenceRecorder


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_browser_playable_person_specific_clip(tmp_path):
    recorder = EvidenceRecorder(EvidenceConfig(clip_pre_seconds=1, clip_post_seconds=2, snapshot_quality=85),
                                snapshot_dir=tmp_path / "screenshots", clip_dir=tmp_path / "clips")
    frame = np.full((120, 160, 3), 100, dtype=np.uint8)
    frames = [(i / 5, frame.copy(), (10, 10, 60, 110)) for i in range(15)]
    path = recorder._encode("person_one", frames, 5)
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                                "-of", "json", str(path)], text=True))
    video = info["streams"][0]
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert 2 <= float(info["format"]["duration"]) <= 3
    recorder.shutdown()
