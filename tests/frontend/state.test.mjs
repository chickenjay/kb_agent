import test from 'node:test';
import assert from 'node:assert/strict';
import {createRunState, beginRun, applyEvent, interruptRun} from '../../web/static/state.js';

test('idle is not completed', () => { assert.equal(createRunState().phase, 'idle'); assert.equal(createRunState().output, null); });
test('tool failure does not finish the whole run', () => {
  const state = applyEvent(beginRun(), {event:'tool_result', run_id:'a', payload:{ok:false}});
  assert.equal(state.phase, 'running'); assert.equal(state.output, null);
});
test('only final makes output available', () => {
  const state = applyEvent(beginRun(), {event:'final', run_id:'a', payload:{output:{status:'needs_clarification'}}});
  assert.equal(state.phase, 'finished'); assert.equal(state.output.status, 'needs_clarification');
});
test('interruption and cancellation are incomplete with no fabricated output', () => {
  const state = interruptRun(beginRun()); assert.equal(state.incomplete, true); assert.equal(state.output, null);
});
test('an incomplete final is never presented as successful answer', () => {
  const state = applyEvent(beginRun(), {event:'final', run_id:'a', payload:{output:{status:'incomplete'}}}); assert.equal(state.incomplete, true);
});
test('events cannot leak into a finished run', () => {
  const state = applyEvent(beginRun(), {event:'final', run_id:'a', payload:{output:{status:'answered'}}});
  assert.throws(() => applyEvent(state, {event:'action', run_id:'a'}));
});
