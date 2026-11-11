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
        script += "$v=Get-LauncherEnvFile (Join-Path $repo 'backend/use_cases/vault_monitoring/.env'); $b=Get-LauncherEnvFile (Join-Path $repo 'backend/use_cases/branch_exterior/.env'); $a=Get-LauncherEnvFile (Join-Path $repo 'backend/services/alert_service/.env'); "
    else:
        script += '''$v=@{ALERT_SERVICE_BASE_URL='http://127.0.0.1:8012';ALERT_SERVICE_TOKEN='vault-test'}; $b=@{ALERT_SERVICE_TOKEN='branch-test'}; $a=@{ALERT_PRODUCER_CREDENTIALS='{"vault-test":{"use_case":"vault_monitoring","producer":"vault-monitoring"},"branch-test":{"use_case":"branch_exterior","producer":"branch-exterior-monitoring"}}'}; '''
    script += extra + '; Get-LauncherGrillGateEnvironment $v $b $a | ConvertTo-Json -Depth 12 -Compress'
    result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',script],capture_output=True,text=True)
    if result.returncode:
        raise ValueError('Provisioning rejected configuration')  # Never print credentials.
    return json.loads(result.stdout)

@pytest.mark.parametrize('local',[False,True])
def test_local_authenticated_publication(tmp_path,local):
    if local and not (ROOT / 'backend/use_cases/vault_monitoring/.env').exists():
        pytest.skip('Local configuration smoke test requires local dotenv')
    config=provision(local=local)
    token=config['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN']
    credentials=json.loads(config['AlertEnvironment']['ALERT_PRODUCER_CREDENTIALS'])
    app=create_app(Settings(database_url=f"sqlite:///{tmp_path / 'alerts.db'}",producer_credentials=credentials,operator_credentials={},notification_webhook_url=''),start_notification_worker=False)
    with TestClient(app) as client:
        for secret,identity in credentials.items():
            response=client.get('/api/v1/producer',headers={'Authorization':'Bearer '+secret})
            assert response.status_code == 200
            assert response.json()['use_case'] == identity['use_case']
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
    assert provision("$v.Remove('ALERT_SERVICE_TOKEN')")['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN'] != token

@pytest.mark.parametrize('extra',["$v.ALERT_SERVICE_BASE_URL='https://example.com'","$v.GRILL_GATE_ALERT_SERVICE_TOKEN='vault-test'","$a.ALERT_PRODUCER_CREDENTIALS='invalid'"])
def test_rejected_configuration(extra):
    with pytest.raises(ValueError):
        provision(extra)

def test_explicit_credential():
    assert provision("$v.GRILL_GATE_ALERT_SERVICE_TOKEN='dedicated'")['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN'] == 'dedicated'


def test_no_existing_credential_generates_private_session_credential():
    extra = "$v.Remove('ALERT_SERVICE_TOKEN'); $b.Remove('ALERT_SERVICE_TOKEN')"
    first = provision(extra)['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN']
    second = provision(extra)['VaultEnvironment']['GRILL_GATE_ALERT_SERVICE_TOKEN']
    assert first != second
    assert len(first) > 40


def test_conflicting_registration_is_not_overwritten():
    with pytest.raises(ValueError):
        provision("$v.GRILL_GATE_ALERT_SERVICE_TOKEN='branch-test'")
