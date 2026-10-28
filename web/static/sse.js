// Streaming TextDecoder is required: UTF-8 characters may cross byte chunks.
export function createSSEParser(onEvent) {
  const decoder = new TextDecoder();
  let buffer = '';
  function parse() {
    let separator;
    while ((separator = /\r?\n\r?\n/.exec(buffer))) {
      const block = buffer.slice(0, separator.index);
      buffer = buffer.slice(separator.index + separator[0].length);
      let name = 'message';
      const data = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith(':')) continue;
        const index = line.indexOf(':');
        const field = index < 0 ? line : line.slice(0, index);
        let value = index < 0 ? '' : line.slice(index + 1);
        if (value.startsWith(' ')) value = value.slice(1);
        if (field === 'event') name = value;
        if (field === 'data') data.push(value);
      }
      if (data.length) onEvent(name, JSON.parse(data.join('\n')));
    }
    if (buffer.length > 2_000_000) throw new Error('事件过大，已停止接收。');
  }
  return {
    push(bytes) { buffer += decoder.decode(bytes, {stream: true}); parse(); },
    finish() { buffer += decoder.decode(); parse(); /* An unterminated block is NOT an event. */ },
  };
}

export async function consumeSSE(response, onEvent) {
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch { /* Keep safe generic message. */ }
    throw new Error(message);
  }
  if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) throw new Error('服务未返回有效的事件流。');
  const reader = response.body.getReader();
  let final = false;
  let runId = null;
  let sequence = 0;
  const parser = createSSEParser((name, event) => {
    if (final || name !== event.event || !Number.isInteger(event.seq) || event.seq <= sequence || (runId && event.run_id !== runId)) throw new Error('事件顺序或运行标识不一致。');
    runId = event.run_id;
    sequence = event.seq;
    if (name === 'final') final = true;
    onEvent(event);
  });
  try {
    while (!final) {
      const {value, done} = await reader.read();
      if (done) { parser.finish(); break; }
      parser.push(value);
    }
    if (!final) throw new Error('连接中断，本次任务未完成。');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
