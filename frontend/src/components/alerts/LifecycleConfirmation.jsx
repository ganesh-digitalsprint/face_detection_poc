import { useEffect, useRef, useState } from 'react';
export default function LifecycleConfirmation({target,initialReason='',pending,onClose,onConfirm}) {
  const dialog=useRef(null);
  const [reason,setReason]=useState(initialReason);
  useEffect(()=>{dialog.current?.showModal();},[]);
  const acknowledging = target === 'ACKNOWLEDGED';
  const label=acknowledging ? 'Acknowledge' : target==='DISMISSED'?'Discard':'Resolve';
  return <dialog ref={dialog} onCancel={onClose} aria-label={`${label} alert confirmation`} className="m-auto w-[min(92vw,440px)] rounded-2xl bg-white p-5 shadow-xl backdrop:bg-black/50">
    <form onSubmit={(e)=>{e.preventDefault();if(reason.trim())onConfirm(reason.trim());}}>
      <h3 className="text-lg font-bold text-[#152449]">{label} this alert?</h3>
      <p className="mt-2 text-sm text-slate-600">{acknowledging ? 'Add a comment for the audit record. The alert will remain in Active.' : 'The alert will move to History. Its evidence will remain available.'}</p>
      <label className="mt-4 block text-sm font-semibold">{acknowledging ? 'Comment' : 'Reason'}<textarea autoFocus required minLength={1} maxLength={500} value={reason} onChange={(e)=>setReason(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 p-2 font-normal" rows={3}/></label>
      <div className="mt-4 flex justify-end gap-2"><button type="button" onClick={onClose} disabled={pending} className="rounded-lg border px-4 py-2">Cancel</button><button type="submit" disabled={pending || !reason.trim()} className="rounded-lg bg-[#34479B] px-4 py-2 text-white disabled:opacity-50">{label} alert</button></div>
    </form>
  </dialog>;
}
