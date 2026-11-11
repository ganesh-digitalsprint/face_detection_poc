import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

test('monitoring panels handle missing snapshots and the uploaded video forwards its confirmed session', async () => {
  const server = await createServer({ root:process.cwd(),server:{ middlewareMode:true },appType:'custom',logLevel:'silent' });
  try {
    const { GateStatePanel, MonitoringStats } = await server.ssrLoadModule('/src/use-cases/grill-gate/components/MonitoringPanels.jsx');
    const { default: UploadedVideoSection } = await server.ssrLoadModule('/src/use-cases/grill-gate/components/UploadedVideoSection.jsx');
    const { EMPTY_MONITORING } = await server.ssrLoadModule('/src/use-cases/grill-gate/grillGateModel.js');
    const store=configureStore({ reducer:{ gateMonitoring:()=>({ sessionId:'video:job-1',gateState:'FULLY_OPEN',direction:null,alertRequests:{},sessions:{} }) } });
    const render=(component,props)=>renderToStaticMarkup(createElement(Provider,{store,stabilityCheck:'never'},createElement(MemoryRouter,null,createElement(component,props))));
    // A missing source must not borrow classification from the currently active session.
    for (const component of [GateStatePanel,MonitoringStats]) {
      for (const monitoring of [undefined,null]) {
        const html=render(component,{monitoring});
        assert.doesNotMatch(html,/aria-current="true"/);
        assert.ok(html.includes('UNKNOWN') || html.includes('Unknown'));
      }
    }
    const html=render(UploadedVideoSection,{videoJob:{job:null},jobs:[],selectedJobId:null,upload:{phase:'idle'},monitoring:{...EMPTY_MONITORING,gateSessionId:'video:job-1'},onSelectJob:()=>{},onJobsChanged:()=>{}});
    // The nested GateStatePanel must receive monitoring, not split monitor/ing props.
    assert.match(html,/aria-current="true"/);
    assert.match(html,/FULLY OPEN/);
    const { default: OpenWithoutCrossingCard } = await server.ssrLoadModule('/src/use-cases/grill-gate/components/OpenWithoutCrossingCard.jsx');
    const recorded=render(OpenWithoutCrossingCard,{gateState:'UNKNOWN',monitoring:{source:'video',gateSessionId:'video:job-1',finalTimer:true,timerRecorded:false,recordedTimerDisplay:{source:'alert',elapsedSeconds:336.341,thresholdSeconds:3,videoTimeSeconds:19.7}}});
    assert.match(recorded,/05:36/);assert.match(recorded,/00:03/);assert.match(recorded,/336.341/);assert.match(recorded,/Recorded alert duration/);
    assert.doesNotMatch(recorded,/Upload the video again/);
    for (const gateState of ['PARTIALLY_OPEN','CLOSED']) {
      const stopped=render(OpenWithoutCrossingCard,{gateState,monitoring:{source:'video',gateSessionId:'video:job-1',cycleStartedAt:null,openWithoutCrossingSeconds:null,openWithoutCrossingThresholdSeconds:3,finalTimer:false}});
      assert.match(stopped,/>00:00<\/p>/);
      assert.match(stopped,/NOT COUNTING/);
      assert.match(stopped,/Gate is/);
      assert.doesNotMatch(stopped,/>\u2014<\/p>/);
    }


  } finally { await server.close(); }
});
