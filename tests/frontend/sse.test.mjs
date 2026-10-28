import test from 'node:test';
import assert from 'node:assert/strict';
import {consumeSSE, createSSEParser} from '../../web/static/sse.js';

const encoder = new TextEncoder();
const event = (name, seq, payload = {}) => ({event:name, seq, run_id:'run-1', payload});
const wire = object => `event: ${object.event}\ndata: ${JSON.stringify(object)}\n\n`;
function response(chunks) { return new Response(new ReadableStream({start(c) { chunks.forEach(s => c.enqueue(encoder.encode(s))); c.close(); }}), {headers:{'Content-Type':'text/event-stream'}}); }

test('UTF-8 Chinese split at every byte with CRLF and heartbeats', () => {
  const received = [];
  const parser = createSSEParser((name, value) => received.push([name, value]));
  const text = ': keep-alive\r\n\r\n' + wire(event('tool_result', 1, {summary:'找到报销制度'})).replaceAll('\n', '\r\n');
  for (const byte of encoder.encode(text)) parser.push(Uint8Array.of(byte));
  parser.finish();
  assert.equal(received.length, 1);
  assert.equal(received[0][1].payload.summary, '找到报销制度');
});
test('multiple events in one chunk and split event delimiter', () => {
  const received = [];
  const parser = createSSEParser((_, value) => received.push(value));
  const text = wire(event('action', 1)) + wire(event('final', 2));
  parser.push(encoder.encode(text.slice(0,-1)));
  assert.equal(received.length, 1);
  parser.push(encoder.encode('\n'));
  assert.equal(received.length, 2);
});
test('unterminated final event never counts as completed', async () => {
  await assert.rejects(consumeSSE(response([wire(event('final', 1)).trimEnd()]), () => {}), /未完成/);
});
test('normal stream finishes exactly once', async () => {
  const received = [];
  await consumeSSE(response([wire(event('run_started', 1)), wire(event('final', 2, {output:{status:'answered'}}))]), e => received.push(e));
  assert.equal(received.length, 2);
});
test('network end without final is failure and makes no second fetch', async () => {
  await assert.rejects(consumeSSE(response([wire(event('run_started', 1))]), () => {}), /未完成/);
});
test('wrong run and out of order sequence are rejected', async () => {
  for (const second of [event('action', 1), {...event('action', 2), run_id:'different'}]) {
    await assert.rejects(consumeSSE(response([wire(event('run_started', 1)) + wire(second)]), () => {}), /不一致/);
  }
});
test('HTTP preflight error remains an error, not a stream', async () => {
  await assert.rejects(consumeSSE(new Response(JSON.stringify({detail:'真实模型未配置'}), {status:503}), () => {}), /未配置/);
});
test('multiline data is joined and comment ignored', () => {
  const received = [];
  const parser = createSSEParser((_, data) => received.push(data));
  parser.push(encoder.encode('event: action\ndata: {"a":\ndata: "中文"}\n: ignore\n\n'));
  assert.deepEqual(received, [{a:'中文'}]);
});
