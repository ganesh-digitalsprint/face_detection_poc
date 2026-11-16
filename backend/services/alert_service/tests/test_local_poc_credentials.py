import json
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from test_alert_api import payload

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows local launcher')

ROOT = Path(__file__).resolve().parents[4]

def provision(extra='', local=False):
    script = "$ErrorActionPreference='Stop'; $repo='" + str(ROOT) + "'; . (Join-Path $repo 'scripts/launcher-common.ps1'); "
    if local:
        script += "$v=Get-LauncherEnvFile (Join-Path $repo 'backend/use_cases/vault_monitoring/.env'); $b=Get-LauncherEnvFile (Join-Path $repo 'backend/use_cases/branch_exterior/.env'); $a=Get-LauncherEnvFile (Join-Path $repo 'backend/services/alert_service/.env'); $v.ALERT_SERVICE_TOKEN=$v.VAULT_ROOM_API_KEY; $v.GRILL_GATE_ALERT_SERVICE_TOKEN=$v.CLOUDINARY_API_KEY; $f=@{ALERT_SERVICE_TOKEN='face-test'}; "
    else:
        script += '''$v=@{ALERT_SERVICE_BASE_URL='http://127.0.0.1:8012';ALERT_SERVICE_TOKEN='vault-test';GRILL_GATE_ALERT_SERVICE_TOKEN='gate-test'}; $b=@{ALERT_SERVICE_TOKEN='branch-test'}; $f=@{ALERT_SERVICE_TOKEN='face-test'}; $a=@{ALERT_PRODUCER_CREDENTIALS='{"vault-test":{"use_case":"vault_monitoring","producer":"vault-monitoring"},"branch-test":{"use_case":"branch_exterior","producer":"branch-exterior-monitoring"}}'}; '''
    script += extra + '; Get-LauncherGrillGateEnvironment -VaultValues $v -BranchValues $b -AlertValues $a -FaceMaskValues $f | ConvertTo-Json -Depth 12 -Compress'
    result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',script],capture_output=True,text=True)
    if result.returncode:
        raise ValueError('Provisioning rejected configuration')  # Never print credentials.
    return json.loads(result.stdout)

@pytest.mark.parametrize('local',[False,True])
def test_local_authenticated_publication(tmp_path,local):
    if local and not (ROOT / 'backend/use_cases/vault_monitoring/.env').exists():
        pytest.skip('Local configuration smoke test requires local dotenv')
    if local:
        branch = (ROOT / 'backend/use_cases/branch_exterior/.env').read_text(encoding='utf-8')
        if not any(line.startswith('ALERT_SERVICE_TOKEN=') and line.partition('=')[2].strip()
                   for line in branch.splitlines()):
            pytest.skip('Local configuration has no dedicated Branch producer credential')
    config=provision(local=local)
    token=config['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN']
    credentials=json.loads(config['AlertEnvironment']['ALERT_PRODUCER_CREDENTIALS'])
    assert {identity['use_case'] for identity in credentials.values()} == {
        'vault_monitoring', 'grill_gate', 'branch_exterior', 'face_mask'}
    app=create_app(Settings(database_url=f"sqlite:///{tmp_path / 'alerts.db'}",producer_credentials=credentials,
        operator_credentials={'operator-test':{'actor_id':'test','use_cases':['*']}},
        notification_webhook_url=''),start_notification_worker=False)
    with TestClient(app) as client:
        event_types = {'vault_monitoring': 'CAMERA_FEED_LOST', 'grill_gate': 'GATE_OPEN_TOO_LONG',
                       'branch_exterior': 'movement', 'face_mask': 'FACE_CONCEALMENT'}
        for secret,identity in credentials.items():
            response=client.get('/api/v1/producer',headers={'Authorization':'Bearer '+secret})
            assert response.status_code == 200
            assert response.json()['use_case'] == identity['use_case']
            use_case = identity['use_case']
            source_id = f'poc-{use_case}'
            created = client.post('/api/v1/alerts', headers={'Authorization':'Bearer '+secret,
                'Idempotency-Key':source_id}, json=payload(source_event_id=source_id,
                source_event_type=event_types[use_case],
                severity='medium' if use_case == 'branch_exterior' else 'WARNING'))
            assert created.status_code == 201
            assert created.json()['use_case'] == use_case
        listed = client.get('/api/v1/alerts?limit=100', headers={'Authorization':'Bearer operator-test'})
        assert listed.status_code == 200
        assert {item['use_case'] for item in listed.json()['items']} == {
            'vault_monitoring', 'grill_gate', 'branch_exterior', 'face_mask'}
        headers={'Authorization':'Bearer '+token,'Idempotency-Key':'poc-test'}
        body=payload(source_event_id='poc-event',source_event_type='GATE_OPEN_TOO_LONG',severity='WARNING')
        first=client.post('/api/v1/alerts',headers=headers,json=body)
        assert first.status_code == 201
        assert first.json()['use_case'] == 'grill_gate'
        replay=client.post('/api/v1/alerts',headers=headers,json=body)
        assert replay.status_code == 200
        assert replay.json()['id'] == first.json()['id']
        forged = dict(body, use_case='vault_monitoring')
        assert client.post('/api/v1/alerts',headers=headers,json=forged).status_code == 422
        assert client.get('/api/v1/producer').status_code == 401

def test_stable_distinct_and_fallback():
    config=provision()
    assert config == provision()
    token=config['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN']
    assert token not in ('vault-test','branch-test')
    assert token == 'gate-test'

@pytest.mark.parametrize('extra',["$v.ALERT_SERVICE_BASE_URL='https://example.com'","$v.GRILL_GATE_ALERT_SERVICE_TOKEN='vault-test'","$a.ALERT_PRODUCER_CREDENTIALS='invalid'"])
def test_rejected_configuration(extra):
    with pytest.raises(ValueError):
        provision(extra)

def test_explicit_credential():
    assert provision("$v.GRILL_GATE_ALERT_SERVICE_TOKEN='dedicated'")['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN'] == 'dedicated'


def test_missing_gate_credential_is_rejected_instead_of_generated():
    with pytest.raises(ValueError):
        provision("$v.Remove('GRILL_GATE_ALERT_SERVICE_TOKEN')")


def test_conflicting_registration_is_not_overwritten():
    with pytest.raises(ValueError):
        provision("$v.GRILL_GATE_ALERT_SERVICE_TOKEN='branch-test'")


def test_branch_requires_explicit_dedicated_credential():
    config = provision("$b.Remove('ALERT_SERVICE_TOKEN'); $a.ALERT_PRODUCER_CREDENTIALS='{}'")
    credentials = json.loads(config['AlertEnvironment']['ALERT_PRODUCER_CREDENTIALS'])
    assert all(identity['use_case'] != 'branch_exterior' for identity in credentials.values())


def test_face_mask_requires_explicit_dedicated_credential():
    config = provision("$f.Remove('ALERT_SERVICE_TOKEN'); $a.ALERT_PRODUCER_CREDENTIALS='{}'")
    credentials = json.loads(config['AlertEnvironment']['ALERT_PRODUCER_CREDENTIALS'])
    assert all(identity['use_case'] != 'face_mask' for identity in credentials.values())


def test_common_alert_database_url_reuses_server_credentials_but_not_vault_database():
    script = ("$ErrorActionPreference='Stop'; . '" + str(ROOT / 'scripts/launcher-common.ps1') +
        "'; Get-LauncherAlertDatabaseUrl 'postgresql+psycopg2://user:encoded%2Fpassword@localhost:5432/face_recognition_db?sslmode=require'")
    result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',script],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == (
        'postgresql+psycopg://user:encoded%2Fpassword@localhost:5432/alert_service?sslmode=require')
