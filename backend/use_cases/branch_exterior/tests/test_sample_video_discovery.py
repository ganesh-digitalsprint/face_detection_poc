import asyncio
from pathlib import Path
from types import SimpleNamespace
from app.core import paths
from app.api.routes import uploads
from app.services import video_folder_sync


def folders(tmp_path,monkeypatch):
    service=tmp_path/'repo'/'backend'/'use_cases'/'branch_exterior'
    current=service/'storage'/'sample_videos'
    legacy=tmp_path/'repo'/'backend'/'branch-exterior-monitoring'/'storage'/'sample_videos'
    for root in [current,legacy]: root.mkdir(parents=True)
    monkeypatch.setattr(paths,'BACKEND_ROOT',service)
    monkeypatch.setattr(paths,'SAMPLE_VIDEO_DIR',current)
    return current,legacy


def test_browse_includes_existing_legacy_and_current_samples_only(tmp_path,monkeypatch):
    current,legacy=folders(tmp_path,monkeypatch)
    (current/'new.MP4').write_bytes(b'video')
    (legacy/'old video.mp4').write_bytes(b'video')
    (legacy/'not-video.txt').write_text('ignore')
    (legacy/'directory.mp4').mkdir()
    monkeypatch.setattr(uploads,'ensure_directories',lambda:None)
    monkeypatch.setattr(uploads,'UPLOAD_DIR',tmp_path/'missing')
    result=asyncio.run(uploads.browse_sample_videos())
    assert {row['name'] for row in result['files']} == {'new.MP4','old video.mp4'}
    assert all(Path(row['path']).is_file() for row in result['files'])


def test_rescan_registers_legacy_samples_once_and_prefers_current_duplicates(tmp_path,monkeypatch):
    current,legacy=folders(tmp_path,monkeypatch)
    (legacy/'old.mp4').write_bytes(b'video')
    (legacy/'same.mp4').write_bytes(b'video')
    (current/'same.mp4').write_bytes(b'video')
    monkeypatch.setattr(video_folder_sync,'ensure_directories',lambda:None)
    saved=[]
    class Cameras:
        async def list(self):return []
        async def create(self,data):saved.append(data);return SimpleNamespace(name=data.name,id='test')
    result=asyncio.run(video_folder_sync._sync_locked(SimpleNamespace(cameras=Cameras()),False))
    assert len(result)==2
    assert {row.source for row in saved} == {str((legacy/'old.mp4').resolve()),str((current/'same.mp4').resolve())}


def test_missing_legacy_directory_does_not_break_current_installation(tmp_path,monkeypatch):
    current,legacy=folders(tmp_path,monkeypatch)
    legacy.rmdir()
    assert paths.sample_video_directories()==[current.resolve()]
