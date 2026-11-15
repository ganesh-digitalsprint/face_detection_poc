import { useEffect, useState } from 'react';
import { resolveAlertEvidence, verifiedEvidence, removeUnavailableSnapshot } from '../api/alertEvidence.js';

const keyFor=(row)=>JSON.stringify([row.id,row.producer,row.useCase,row.sourceEventId,row.rowVersion,row.sourceEventVersion,row.confirmedSourceVersion,row.evidenceRefs,row.primaryEvidenceId]);
const EMPTY=[];

export default function useAlertEvidence(items,resolve=resolveAlertEvidence) {
  const rows=items.length ? items : EMPTY;
  const [records,setRecords]=useState({});
  useEffect(()=>{
    const ctl=new AbortController();let next=0;
    const activeKeys=new Set(rows.map(keyFor));
    setRecords((old)=>Object.fromEntries(Object.entries(old).filter(([key])=>activeKeys.has(key))));
    const worker=async()=>{
      while(next<rows.length && !ctl.signal.aborted) {
        const row=rows[next++];
        try {
          const evidence=await resolve(row,ctl.signal);
          if(!ctl.signal.aborted)setRecords((old)=>({...old,[keyFor(row)]:evidence}));
        } catch { /* Superseded requests never update another filter's rows. */ }
      }
    };
    for(let i=0;i<Math.min(4,rows.length);i+=1)worker();
    return ()=>ctl.abort();
  },[rows,resolve]);
  return items.map((row)=>{
    const key=keyFor(row);
    const evidence=records[key] || {...verifiedEvidence([],[],true),evidenceChecked:false};
    return {...row,...evidence,onEvidenceError:(url)=>setRecords((old)=>{
      const current=old[key];if(!current)return old;
      const updated=removeUnavailableSnapshot(current,url);
      return updated===current ? old : {...old,[key]:updated};
    })};
  });
}
