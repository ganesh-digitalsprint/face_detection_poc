import { LockKeyhole, ScanFace } from 'lucide-react';
import Button from '../components/common/Button.jsx';
import Card from '../components/common/Card.jsx';
import CameraPreview from '../components/vault/CameraPreview.jsx';
import CameraSourceSelector from '../components/vault/CameraSourceSelector.jsx';
import SecurityVerificationPanel from '../components/vault/SecurityVerificationPanel.jsx';
import useCameraSource from '../hooks/useCameraSource.js';
import useVaultAccess from '../hooks/useVaultAccess.js';

/** Vault Access: any camera source -> backend liveness -> recognition -> authorization -> decision. */
export default function VaultAccess() {
  const camera = useCameraSource();
  const vault = useVaultAccess(camera);
  const verifying = vault.phase === 'starting' || vault.phase === 'liveness';
  const idle = vault.phase === 'idle';

  const handleStop = () => { vault.reset(); camera.stop(); };
  const stopCamera = { ...camera, stop: handleStop };

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center gap-2 text-navy">
        <LockKeyhole className="h-5 w-5" aria-hidden />
        <h2 className="text-lg font-semibold">PGM Vault Access</h2>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Camera">
          <div className="space-y-4">
            <CameraPreview camera={camera} />
            <CameraSourceSelector camera={stopCamera} disabled={verifying} />
            {camera.status === 'ready' && idle && (
              <Button icon={ScanFace} onClick={vault.start}>Start Verification</Button>
            )}
          </div>
        </Card>
        <Card title="Security Verification">
          {idle ? (
            <p className="text-sm text-slate-500">
              Start a camera, then begin verification. The system checks face, liveness, identity and
              authorization before any access decision.
            </p>
          ) : (
            <SecurityVerificationPanel vault={vault} onRetry={vault.start} />
          )}
        </Card>
      </div>
    </div>
  );
}
