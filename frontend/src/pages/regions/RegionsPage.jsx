import { lazy, Suspense } from 'react';
import { Moon, Sun } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import Loading from '../../components/common/Loading.jsx';
import { Empty } from '../../use-cases/branch-exterior/components/ui.jsx';
import { toggleTheme, useBxTheme } from '../../use-cases/branch-exterior/theme.js';
import '../../use-cases/branch-exterior/branchExterior.css';
import ZonesOverview from './ZonesOverview.jsx';
import { parseUseCase, USE_CASES } from './regionsModel.js';

// Each use case's editor loads on demand, and only when selected, so a stopped service never blocks the others.
const BranchZones = lazy(() => import('../../use-cases/branch-exterior/pages/RegionsZonesPage.jsx'));
const FaceMaskZones = lazy(() => import('../../use-cases/face-mask/components/EntryRoiPanel.jsx'));

/** Common Regions & Zones: choose a use case, then draw and manage that use case's zones. */
export default function RegionsPage() {
  const [params, setParams] = useSearchParams();
  const useCase = parseUseCase(params.get('use_case'));
  const theme = useBxTheme();
  const next = theme === 'dark' ? 'bright' : 'dark';

  const select = (id, camera) => setParams(() => {
    const query = new URLSearchParams();
    if (id !== 'all') query.set('use_case', id);
    if (camera && id === 'face_mask') query.set('camera', camera);
    return query;
  });

  return (
    <div className="bx-page" data-theme={theme}>
      <div className="bx-subbar">
        <p className="sub" style={{ margin: 0, maxWidth: 760 }}>
          Zones for every use case in one place. Pick a use case, choose a camera and draw the area; changes reach running streams without a restart.
        </p>
        <button type="button" className="bx-btn bx-btn-sm bx-no-print" onClick={toggleTheme} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
          {theme === 'dark' ? <Sun size={14} aria-hidden /> : <Moon size={14} aria-hidden />}
        </button>
      </div>
      <div className="bx-row bx-gap-8 bx-wrap bx-mb-16" role="group" aria-label="Use case">
        {USE_CASES.map((u) => (
          <button key={u.id} type="button" className={`bx-btn ${useCase === u.id ? 'bx-btn-primary' : ''}`} aria-pressed={useCase === u.id} onClick={() => select(u.id)}>
            {u.label}
          </button>
        ))}
      </div>
      <Suspense fallback={<Loading message="Loading zones…" />}>
        {useCase === 'all' && <ZonesOverview useCase="all" onOpen={select} />}
        {useCase === 'vault_access' && <Empty icon="🔒">Vault Access has no drawable zones yet. Door authorization does not use regions.</Empty>}
        {useCase === 'branch_exterior' && <BranchZones />}
        {useCase === 'face_mask' && <FaceMaskZones />}
      </Suspense>
    </div>
  );
}
