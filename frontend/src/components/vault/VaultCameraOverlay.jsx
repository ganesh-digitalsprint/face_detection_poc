import { Loader2, RotateCcw, ScanFace, ShieldCheck, ShieldX } from 'lucide-react';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import { formatMmSs } from '../../utils/dualControl.js';
import { VAULT_VIEW, WINDOW_WARNING_SECONDS, activeSlot, handoffSubject } from '../../utils/vaultView.js';
import { denialReason, REASONS } from './AccessDecision.jsx';
import { feedbackText } from './LivenessStatus.jsx';
import { challengeUI } from './challengeUI.js';

const LIVE_VIEWS = [VAULT_VIEW.STARTING, VAULT_VIEW.LIVENESS, VAULT_VIEW.IDENTITY, VAULT_VIEW.HANDOFF];
const chip = 'absolute top-3 z-10 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold sm:top-4 sm:text-sm';
const actionButton = 'mt-5 inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-5 text-sm font-semibold';

function FaceGuide() {
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
      <ellipse cx="50" cy="45" rx="19" ry="27" fill="none" stroke="white" strokeOpacity="0.85"
        strokeWidth="2.5" strokeDasharray="10 8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function PromptCard({ label, children }) {
  return (
    <div role="status" aria-live="polite"
      className="absolute inset-x-4 bottom-4 z-10 mx-auto max-w-md rounded-xl bg-white px-5 py-3 text-center shadow-lg sm:bottom-6">
      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#34479B]">{label}</p>
      {children}
    </div>
  );
}

function ChallengeCard({ vault, slot }) {
  const { instruction } = challengeUI(vault.challenge);
  const wrong = vault.liveness?.feedback === 'WRONG_DIRECTION';
  return (
    <PromptCard label={`Custodian ${slot} · Liveness`}>
      <p className="mt-1 text-xl font-bold text-[#0F1B3D] sm:text-2xl">{instruction}</p>
      <p className={`mt-1 text-sm ${wrong ? 'font-semibold text-[#6B4500]' : 'text-[#55607A]'}`}>
        {feedbackText(vault.liveness)}
      </p>
    </PromptCard>
  );
}

function HandoffOverlay({ vault }) {
  const name = handoffSubject(vault);
  const duplicate = vault.result?.reason === 'DUPLICATE_EMPLOYEE_REJECTED';
  const count = vault.handoffRemaining;
  return (
    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-[#0B1224]/85 px-6 text-center text-white">
      {/* Only the instruction is announced; the ticking number would interrupt every second. */}
      <div role="status" aria-live="assertive">
        {duplicate ? (
          <p className="max-w-md text-base font-semibold sm:text-lg">
            <ShieldX className="mr-1 inline h-5 w-5 align-[-3px]" aria-hidden />
            {`${name ?? 'This employee'} is already verified. A different employee must complete the next verification.`}
          </p>
        ) : (
          <p className="max-w-md text-base font-semibold sm:text-lg">
            <ShieldCheck className="mr-1 inline h-5 w-5 align-[-3px]" aria-hidden />
            {name ? `${name} verified. ` : 'Custodian verified. '}Please step away.
          </p>
        )}
        <p className="mt-2 text-sm text-slate-200">Next custodian step in.</p>
      </div>
      <p className="mt-4 text-7xl font-bold tabular-nums sm:text-8xl" aria-hidden>
        {count > 0 ? count : <Loader2 className="h-16 w-16 animate-spin motion-reduce:animate-none" aria-hidden />}
      </p>
      <p className="mt-2 text-xs text-slate-300">
        {count > 0 ? 'Next verification starts automatically' : 'Starting the next challenge…'}
      </p>
    </div>
  );
}

function ResultOverlay({ granted, title, detail, actionLabel, onAction }) {
  const Icon = granted ? ShieldCheck : ShieldX;
  const tone = granted ? 'bg-[#0B7A4B]/92' : 'bg-[#B3261E]/92';
  return (
    <div role="alert" className={`absolute inset-0 z-20 flex flex-col items-center justify-center px-6 text-center text-white ${tone}`}>
      <Icon className="h-14 w-14" aria-hidden />
      <p className="mt-3 text-2xl font-bold tracking-wide sm:text-3xl">{title}</p>
      {detail && <p className="mt-2 max-w-md text-sm sm:text-base">{detail}</p>}
      <button type="button" onClick={onAction}
        className={`${actionButton} bg-white ${granted ? 'text-[#0B6B43]' : 'text-[#B3261E]'} hover:bg-slate-100`}>
        <RotateCcw className="h-4 w-4" aria-hidden /> {actionLabel}
      </button>
    </div>
  );
}

function resultProps(view, vault) {
  if (view === VAULT_VIEW.GRANTED) {
    return {
      granted: true, title: 'VAULT ACCESS GRANTED',
      detail: vault.requiredCount === 1 ? 'Custodian verified. All required checks passed.' : 'Dual control verified.',
      actionLabel: 'Start new session',
    };
  }
  if (view === VAULT_VIEW.TIMEOUT) {
    return { granted: false, title: 'SESSION EXPIRED', detail: REASONS.DUAL_AUTHENTICATION_TIMEOUT, actionLabel: 'Try again' };
  }
  if (view === VAULT_VIEW.CANCELLED) {
    return { granted: false, title: 'SESSION CANCELLED', detail: 'The vault access session was cancelled.', actionLabel: 'Try again' };
  }
  return {
    granted: false, title: 'ACCESS DENIED',
    detail: vault.endReason ?? denialReason(vault.result, vault.liveness), actionLabel: 'Try again',
  };
}

/** Everything drawn over the live video. Pure presentation of hook state. */
export default function VaultCameraOverlay({ camera, vault, view, onStart, onReady }) {
  const cameraOn = camera.status === 'ready';
  const live = LIVE_VIEWS.includes(view);
  const slot = activeSlot(vault, view);
  const remaining = vault.remainingSeconds;
  const urgent = remaining != null && remaining < WINDOW_WARNING_SECONDS;
  const terminal = [VAULT_VIEW.GRANTED, VAULT_VIEW.DENIED, VAULT_VIEW.TIMEOUT, VAULT_VIEW.CANCELLED].includes(view);

  return (
    <>
      {cameraOn && !terminal && <FaceGuide />}
      {cameraOn && (
        <span className={`${chip} left-3 bg-black/55 text-white sm:left-4`}>
          <span className="h-2 w-2 rounded-full bg-red-500" aria-hidden />
          Live · {camera.kind === CAMERA_KINDS.CCTV ? 'CCTV' : 'Webcam'}
        </span>
      )}
      {live && remaining != null && (
        <span className={`${chip} right-3 tabular-nums sm:right-4 ${urgent ? 'bg-[#FFF4DC] text-[#6B4500] ring-2 ring-[#6B4500]' : 'bg-white text-[#0F1B3D]'}`}>
          Window {formatMmSs(remaining)} left
        </span>
      )}

      {view === VAULT_VIEW.IDLE && cameraOn && (
        <div className="absolute inset-x-4 bottom-4 z-10 flex flex-wrap items-center justify-center gap-2 sm:bottom-6">
          {vault.config?.allow_mode_select ? (
            <label className="flex min-h-11 items-center gap-2 rounded-md bg-white px-3 text-sm font-medium text-[#0F1B3D] shadow-lg">
              Required custodians:
              <select aria-label="Required custodians" value={vault.selectedRequiredPersons ?? vault.config.required_persons}
                disabled={vault.phase !== 'idle'}
                onChange={(event) => vault.selectRequiredPersons(Number(event.target.value))}
                className="min-h-9 rounded border border-slate-300 bg-white px-2">
                <option value={1}>1</option><option value={2}>2</option>
              </select>
            </label>
          ) : (
            <span className="rounded-md bg-white px-3 py-3 text-sm font-medium text-[#0F1B3D] shadow-lg">
              {vault.config?.required_persons === 1 ? 'Single-custodian test mode' : 'Two-person authorization required'}
            </span>
          )}
          <button type="button" onClick={onStart} disabled={!vault.config || vault.configLoading}
            className="inline-flex min-h-11 items-center gap-2 rounded-md bg-[#34479B] px-5 text-sm font-semibold text-white shadow-lg hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-60">
            <ScanFace className="h-4 w-4" aria-hidden /> Start vault access
          </button>
        </div>
      )}
      {view === VAULT_VIEW.STARTING && (
        <div role="status" className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-[#0B1224]/70 text-white">
          <Loader2 className="h-10 w-10 animate-spin motion-reduce:animate-none" aria-hidden />
          <p className="text-sm font-medium">Starting secure session…</p>
        </div>
      )}
      {view === VAULT_VIEW.LIVENESS && vault.challenge && <ChallengeCard vault={vault} slot={slot} />}
      {view === VAULT_VIEW.IDENTITY && (
        <PromptCard label={`Custodian ${slot} · Identity`}>
          <p className="mt-1 text-lg font-bold text-[#0F1B3D] sm:text-xl">{REASONS.LOOK_AT_CAMERA}</p>
        </PromptCard>
      )}
      {view === VAULT_VIEW.HANDOFF && <HandoffOverlay vault={vault} />}
      {terminal && <ResultOverlay {...resultProps(view, vault)} onAction={onReady} />}
    </>
  );
}
