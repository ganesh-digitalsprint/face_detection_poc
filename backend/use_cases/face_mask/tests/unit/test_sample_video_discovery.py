import asyncio
from pathlib import Path
from app.services import sources
from app.api.routes import uploads


def test_legacy_videos_are_listed_and_resolve_for_processing(tmp_path,monkeypatch):
    storage=tmp_path/'legacy-storage'; samples=storage/'sample_videos';samples.mkdir(parents=True)
    video=samples/'My sample.MP4';video.write_bytes(b'video')
    (samples/'ignore.txt').write_text('ignore')
    monkeypatch.setattr(sources,'_LEGACY_BRANCH_STORAGE',storage)
    monkeypatch.setattr(sources,'_BRANCH_STORAGE',tmp_path/'missing')
    monkeypatch.setattr(sources,'REPO_ROOT',tmp_path/'repo')
    monkeypatch.setattr(sources,'SAMPLE_VIDEO_DIR',tmp_path/'ours')
    monkeypatch.setattr(sources,'UPLOAD_DIR',tmp_path/'uploads')
    assert sources.resolve_video_path(str(video))==video.resolve()
    rows=asyncio.run(uploads.browse_videos())
    assert any(row.name==video.name and sources.resolve_video_path(row.path)==video.resolve() for row in rows)
    outside=tmp_path/'private.mp4';outside.write_bytes(b'video')
    assert sources.resolve_video_path(str(outside)) is None


def test_missing_legacy_folder_is_ignored_and_paths_are_deduplicated(tmp_path,monkeypatch):
    shared=tmp_path/'storage';(shared/'sample_videos').mkdir(parents=True)
    monkeypatch.setattr(sources,'_LEGACY_BRANCH_STORAGE',shared)
    monkeypatch.setattr(sources,'_BRANCH_STORAGE',shared)
    roots=sources.video_roots()
    assert roots.count((shared/'sample_videos').resolve())==1
