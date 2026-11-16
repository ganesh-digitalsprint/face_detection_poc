import sqlite3
from pathlib import Path

from fedbank_core.events.metadata import enrich_resource_refs


def platform_db(path: Path):
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE zones(id TEXT PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE cities(id TEXT PRIMARY KEY,name TEXT NOT NULL,zone_id TEXT NOT NULL);
            CREATE TABLE branches(id TEXT PRIMARY KEY,code TEXT,name TEXT,city_id TEXT,manager TEXT);
            CREATE TABLE cameras(id TEXT PRIMARY KEY,name TEXT,branch_id TEXT);
            CREATE TABLE camera_use_cases(camera_id TEXT,use_case TEXT);
            CREATE TABLE legacy_camera_links(use_case TEXT,legacy_id TEXT,branch_id TEXT);
            INSERT INTO zones VALUES('zone-1','West');
            INSERT INTO cities VALUES('city-1','Pune','zone-1');
            INSERT INTO branches VALUES('branch-1','P001','Central','city-1','A. Manager');
            INSERT INTO cameras VALUES('camera-1','Front entrance','branch-1');
            INSERT INTO camera_use_cases VALUES('camera-1','branch_exterior');
            INSERT INTO legacy_camera_links VALUES('branch_exterior','legacy-camera','branch-1');
        ''')


def test_registered_branch_camera_resolves_complete_canonical_context(tmp_path, monkeypatch):
    path = tmp_path / 'platform.db'
    platform_db(path)
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(path))

    refs = enrich_resource_refs('branch_exterior', {'camera_id': 'camera-1'})

    assert refs == {'camera_id': 'camera-1', 'branch_id': 'branch-1', 'branch_code': 'P001',
        'branch_name': 'Central', 'camera_name': 'Front entrance', 'place_name': 'Pune',
        'region_name': 'West', 'branch_manager': 'A. Manager'}


def test_legacy_camera_link_resolves_branch_details_without_replacing_source_camera_id(tmp_path, monkeypatch):
    path = tmp_path / 'platform.db'
    platform_db(path)
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(path))

    refs = enrich_resource_refs('branch_exterior', {'camera_id': 'legacy-camera', 'zone_name': 'Whole scene'})

    assert refs['camera_id'] == 'legacy-camera'
    assert refs['branch_id'] == 'branch-1'
    assert refs['branch_code'] == 'P001'
    assert refs['branch_name'] == 'Central'
    assert refs['place_name'] == 'Pune'
    assert refs['region_name'] == 'West'
    assert refs['branch_manager'] == 'A. Manager'
    assert refs['zone_name'] == 'Whole scene'
    assert 'camera_name' not in refs


def test_existing_attribution_is_not_overwritten_by_a_different_camera_branch(tmp_path, monkeypatch):
    path = tmp_path / 'platform.db'
    platform_db(path)
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(path))

    refs = enrich_resource_refs('branch_exterior', {'camera_id': 'camera-1', 'branch_id': 'other-branch'})

    assert refs == {'camera_id': 'camera-1', 'branch_id': 'other-branch'}
