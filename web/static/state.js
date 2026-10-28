export function createRunState() { return {phase: 'idle', events: [], output: null, incomplete: false, runId: null}; }
export function beginRun() { return {...createRunState(), phase: 'running'}; }
export function applyEvent(state, event) {
  if (state.phase !== 'running') throw new Error('当前没有可接收事件的任务。');
  if (state.runId && state.runId !== event.run_id) throw new Error('运行标识不一致。');
  const next = {...state, runId: event.run_id, events: [...state.events, event]};
  if (event.event === 'final') {
    next.output = event.payload.output;
    next.phase = 'finished';
    next.incomplete = next.output.status === 'incomplete';
  }
  return next;
}
export function interruptRun(state) { return {...state, phase: 'interrupted', incomplete: true, output: null}; }
