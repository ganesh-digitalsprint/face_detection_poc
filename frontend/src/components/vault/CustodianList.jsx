import { Info, UserRound } from 'lucide-react';
import { formatClockTime } from '../../utils/vaultView.js';

function VerifiedCustodian({ custodian }) {
  const meta = [custodian.employee_id && `Employee ID ${custodian.employee_id}`, custodian.designation, custodian.department]
    .filter(Boolean)
    .join(' · ');
  return (
    <li className="custodian-enter flex gap-3 rounded-xl border border-[#BFE5D1] bg-[#F2FBF6] p-4">
      <span aria-hidden className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#0B7A4B] text-base font-bold text-white">
        {custodian.name.trim().charAt(0).toUpperCase()}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="truncate text-base font-semibold text-[#0F1B3D]">{custodian.name}</p>
          {custodian.authorization_active && (
            <span className="rounded-full bg-[#E6F6EE] px-2.5 py-1 text-[11px] font-bold tracking-wide text-[#0B6B43]">
              AUTHORIZATION ACTIVE
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-[#55607A]">{meta}</p>
        <p className="mt-1 text-xs text-[#55607A]">
          Custodian {custodian.slot} · verified <time dateTime={custodian.verified_at}>{formatClockTime(custodian.verified_at)}</time>
          {' '}· face, liveness, identity
        </p>
      </div>
    </li>
  );
}

function EmptySlot({ slot, inProgress }) {
  return (
    <li className="flex gap-3 rounded-xl border border-dashed border-[#D9DEEB] p-4">
      <span aria-hidden className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#F4F6FB] text-[#55607A]">
        <UserRound className="h-5 w-5" />
      </span>
      <div>
        <p className="text-base font-semibold text-[#0F1B3D]">Custodian {slot}</p>
        <p className="text-sm text-[#55607A]">
          {inProgress ? 'Verifying now. A different employee must complete all checks.' : 'Waiting'}
        </p>
      </div>
    </li>
  );
}

/**
 * Verified custodians in the order the backend accepted them, then placeholders up to `requiredCount`.
 * Either employee may go first; slots are numbered only by verification order.
 */
export default function CustodianList({ custodians, requiredCount, activeSlot, handoff = false, handoffName = null }) {
  const emptySlots = Array.from(
    { length: Math.max(0, requiredCount - custodians.length) },
    (_, index) => custodians.length + index + 1,
  );
  return (
    <section aria-labelledby="vault-custodians-title" className="vault-card p-5">
      <h2 id="vault-custodians-title" className="vault-heading text-base">Authorized custodians</h2>
      <ul className="mt-3 space-y-3" aria-live="polite">
        {custodians.map((custodian) => <VerifiedCustodian key={custodian.employee_id} custodian={custodian} />)}
        {emptySlots.map((slot) => <EmptySlot key={slot} slot={slot} inProgress={slot === activeSlot} />)}
      </ul>
      {handoff && (
        <p className="mt-3 flex gap-2 rounded-lg bg-[#EAF0FF] p-3 text-sm text-[#1F2F6B]">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            Next custodian: step in when the countdown ends.
            {handoffName ? ` ${handoffName}, please step away.` : ' The verified custodian should step away.'}
          </span>
        </p>
      )}
    </section>
  );
}
