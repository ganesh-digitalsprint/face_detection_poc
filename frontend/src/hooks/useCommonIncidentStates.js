import { useEffect, useState } from 'react';
import { listServiceAlerts } from '../api/alertService.js';

/** Branch/Face review records remain intact; this is their Common incident status read model. */
export default function useCommonIncidentStates(useCase) {
  const [state,setState]=useState({key:useCase,bySource:{},error:false});
  useEffect(()=>{
    let active=true,running=false;
    const ctl=new AbortController();
    const refresh=async()=>{
      if(running || document.visibilityState==='hidden')return;
      running=true;
      try {
        const rows=[];let cursor;
        do {const page=await listServiceAlerts({use_case:useCase,limit:100,...(cursor?{cursor}:{})},ctl.signal);rows.push(...page.items);cursor=page.nextCursor;}while(cursor && active);
        if(active)setState({key:useCase,bySource:Object.fromEntries(rows.map((row)=>[row.sourceEventId,row])),error:false});
      }catch{if(active)setState((old)=>({...old,error:true}));}finally{running=false;}
    };
    refresh();const timer=window.setInterval(refresh,5000);
    document.addEventListener('visibilitychange',refresh);
    return()=>{active=false;ctl.abort();window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
  },[useCase]);
  return state.key===useCase?state:{bySource:{},error:false};
}
