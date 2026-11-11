import { test } from 'node:test';
import assert from 'node:assert/strict';
import client from '../../api/client.js';
import { getGrillGateSnapshot } from './api/grillGate.js';

test('snapshot retrieval uses the existing Vault client, source-scoped path and binary response', async () => {
  const previous=client.defaults.adapter;
  const blob=new Blob([new Uint8Array([255,216,255,217])],{ type:'image/jpeg' });
  let received;
  client.defaults.adapter=async(config)=>{received=config;return{ data:blob,status:200,statusText:'OK',headers:{},config };};
  try {
    const controller=new AbortController();
    const result=await getGrillGateSnapshot({ retrieval_path:'/api/v1/grill-gate/alerts/local-id/evidence/image-id?assignment_id=assignment-1' },controller.signal);
    assert.equal(result,blob);assert.equal(received.responseType,'blob');assert.equal(received.signal,controller.signal);
    assert.equal(received.url,'/api/v1/grill-gate/alerts/local-id/evidence/image-id');
    assert.deepEqual(received.params,{ assignment_id:'assignment-1' });
    assert.equal(received.baseURL,client.defaults.baseURL);
    assert.ok(!received.url.includes('token'));
    client.defaults.adapter=async(config)=>({ data:new Blob(['error'],{ type:'text/html' }),status:200,headers:{},config });
    await assert.rejects(getGrillGateSnapshot({retrieval_path:'/api/v1/grill-gate/alerts/a/evidence/e?video_job_id=v'}),/not an image/);
    await assert.rejects(getGrillGateSnapshot({retrieval_path:'https://arbitrary.example/image.jpg'}),/unavailable/);
  } finally { client.defaults.adapter=previous; }
});
