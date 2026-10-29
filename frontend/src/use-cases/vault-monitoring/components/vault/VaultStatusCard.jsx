import { LockKeyhole, LockKeyholeOpen } from 'lucide-react';

/** Granted only when the backend says `access_granted === true`. */
export default function VaultStatusCard({ result, requiredCount }) {
  const granted = result?.access_granted === true;
  const Icon = granted ? LockKeyholeOpen : LockKeyhole;
  return (
    <section
      aria-label="Vault status"
      aria-live="polite"
      className={`vault-card flex items-center gap-4 p-5 ${granted ? 'border-[#BFE5D1] bg-[#E6F6EE]' : ''}`}
    >
      <span aria-hidden className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ${
        granted ? 'bg-[#0B7A4B] text-white' : 'bg-[#F4F6FB] text-[#55607A]'
      }`}>
        <Icon className="h-6 w-6" />
      </span>
      <div>
        <p className={`text-lg font-bold tracking-wide ${granted ? 'text-[#0B6B43]' : 'text-[#0F1B3D]'}`}>
          {granted ? 'VAULT ACCESS GRANTED' : 'VAULT LOCKED'}
        </p>
        <p className={`text-sm ${granted ? 'text-[#0B6B43]' : 'text-[#55607A]'}`}>
          {requiredCount == null
            ? 'Loading authorization requirements.'
            : granted
            ? `${requiredCount} of ${requiredCount} ${requiredCount === 1 ? 'custodian' : 'custodians'} verified. ${requiredCount === 1 ? 'All required checks passed.' : 'Dual control satisfied.'}`
            : `Opens when ${requiredCount} of ${requiredCount} ${requiredCount === 1 ? 'custodian is' : 'custodians are'} verified`}
        </p>
      </div>
    </section>
  );
}
