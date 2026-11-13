import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { normalizeGrillGateAlert } from '../../../api/alertServiceModel.js';

test('right-side card matches the compact reference and opens the existing selected incident',async()=>{
  const server=await createServer({root:process.cwd(),server:{middlewareMode:true},appType:'custom',logLevel:'silent'});
  try {
    const {default:Card}=await server.ssrLoadModule('/src/use-cases/grill-gate/components/GrillGateAlertCard.jsx');
    const alert=normalizeGrillGateAlert({id:'saved-1',source_event_id:'source-1',source_event_type:'GATE_OPEN_TOO_LONG',severity:'WARNING',status:'OPEN',summary:'Gate remained open without a completed ENTRY or EXIT crossing for 3.003 seconds.',evidence_refs:[]});
    let selected;
    const props={alert,selected:false,onSelect:(id)=>{selected=id;}};
    const html=renderToStaticMarkup(createElement(Card,props));
    assert.match(html,/border-l-\[\#F59E0B\]/);
    assert.match(html,/rounded-\[20px\]/);
    assert.match(html,/lucide-camera/);
    assert.match(html,/lucide-chevron-right/);
    assert.match(html,/<strong[^>]*text-\[\#B45309\][^>]*>3\.003 seconds<\/strong>/);
    assert.equal((html.match(/<button/g)||[]).length,1,'snapshot and chevron share the card details action without nested buttons');
    assert.doesNotMatch(html,/View details|Grill Gate Monitoring/);
    const tree=Card(props);
    tree.props.children[0].props.onClick();
    assert.equal(selected,'saved-1');
    for(const severity of ['HIGH','CRITICAL','INFO','CUSTOM']) {
      const other=renderToStaticMarkup(createElement(Card,{...props,alert:{...alert,severity,status:'RESOLVED'},selected:true}));
      assert.ok(other.includes(severity));assert.match(other,/aria-pressed="true"/);assert.match(other,/RESOLVED/);
    }
    const captured={...alert,evidenceStatus:'CAPTURED',evidenceRefs:[{type:'snapshot',retrieval_path:'/api/v1/grill-gate/alerts/saved-1/evidence/frame-1?video_job_id=job-1'}]};
    const pending=renderToStaticMarkup(createElement(Card,{...props,alert:captured}));
    assert.match(pending,/Loading snapshot/);
    assert.doesNotMatch(pending,/<img[^>]+https?:/,'no fabricated CCTV image');
  } finally {await server.close();}
});
