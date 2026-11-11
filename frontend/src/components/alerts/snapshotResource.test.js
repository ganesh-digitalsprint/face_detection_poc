import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadSnapshot } from './snapshotResource.js';
const tick = () => new Promise((resolve) => setImmediate(resolve));

test('loads a binary JPEG, publishes its object URL and releases it on cleanup', async () => {
  const states=[], released=[];
  const blob=new Blob([new Uint8Array([255,216,255,217])],{ type:'image/jpeg' });
  const stop=loadSnapshot({ ref:{ id:'real-evidence' }, fetchBlob:async(ref,signal)=>{ assert.equal(ref.id,'real-evidence'); assert.equal(signal.aborted,false); return blob; },onChange:(state)=>states.push(state),urls:{ createObjectURL:(value)=>{ assert.equal(value,blob); return 'blob:snapshot'; },revokeObjectURL:(url)=>released.push(url) } });
  await tick(); assert.equal(states.at(-1).url,'blob:snapshot'); stop(); assert.deepEqual(released,['blob:snapshot']);
});

test('navigation cancels stale snapshot response without leaking an object URL', async () => {
  let finish, signal; const states=[];
  const stop=loadSnapshot({ ref:{},fetchBlob:(_,s)=>{ signal=s; return new Promise((resolve)=>{finish=resolve;}); },onChange:(value)=>states.push(value),urls:{createObjectURL:()=>{throw new Error('Stale response must not create URL');}} });
  await tick(); stop(); assert.equal(signal.aborted,true); finish(new Blob()); await tick(); assert.equal(states.length,1);
});

test('retrieval failures produce an evidence fallback instead of hiding the incident', async () => {
  const states=[];
  const stop=loadSnapshot({ ref:{},fetchBlob:async()=>{throw new Error('404');},onChange:(value)=>states.push(value) });
  await tick(); assert.equal(states.at(-1).error,'Snapshot could not be retrieved.'); assert.equal(states.at(-1).loading,false); stop();
});
