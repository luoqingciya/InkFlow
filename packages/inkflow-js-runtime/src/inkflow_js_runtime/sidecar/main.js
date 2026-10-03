/**
 * InkFlow JS sidecar 入口。
 *
 * 协议：**JSON Lines over stdio**，一行一条消息。
 *
 * Python → sidecar：
 *   {"id": 1, "method": "eval",     "params": {"code": "...", "timeout": 15000, "vars": {...}}}
 *   {"id": 2, "method": "ping"}
 *   {"id": 3, "method": "shutdown"}
 *
 * sidecar → Python（响应）：
 *   {"id": 1, "ok": true,  "result": "..."}
 *   {"id": 1, "ok": false, "error": {"kind": "timeout", "message": "..."}}
 *
 * sidecar → Python（反向请求，用于 java.ajax）：
 *   {"id": "host-1", "method": "host.request", "params": {"url": "...", "method": "GET"}}
 * Python 必须回一条 {"id": "host-1", "result": {...}}。
 *
 * **stdout 是协议通道，日志一律走 stderr** —— 混在一起会让 JSON 行解析失败。
 */

import { readLineSync, writeLog, writeMessage } from './channel.js';
import { createJavaApi } from './host.js';
import { runInSandbox } from './sandbox.js';

let hostRequestSeq = 0;

/**
 * 同步回调 Python 发一个网络请求。
 *
 * 写请求 → 阻塞读响应。因为 Python 是独立进程，阻塞期间它能正常处理，
 * 不会死锁。
 */
function hostRequest(payload) {
  hostRequestSeq += 1;
  const id = `host-${hostRequestSeq}`;

  writeMessage({ id, method: 'host.request', params: payload });

  const line = readLineSync();
  if (line === null) {
    throw new Error('Python 侧已关闭连接');
  }

  let message;
  try {
    message = JSON.parse(line);
  } catch {
    throw new Error(`host.request 收到无法解析的响应：${line.slice(0, 200)}`);
  }

  if (message.id !== id) {
    throw new Error(`协议错乱：期望响应 ${id}，收到 ${String(message.id)}`);
  }

  return message.result ?? { ok: false, error: 'Python 未返回结果' };
}

/** 把 JS 值转成能塞进 JSON 的形式。 */
function normalize(value) {
  if (value === undefined || value === null) {
    return null;
  }
  const type = typeof value;
  if (type === 'string' || type === 'number' || type === 'boolean') {
    return value;
  }
  if (type === 'bigint') {
    return value.toString();
  }
  try {
    // 走一遍 JSON 往返：既验证可序列化，也顺手剥掉不可传的东西
    return JSON.parse(JSON.stringify(value));
  } catch {
    return String(value);
  }
}

/** 把异常归类，便于 Python 侧区分「超时」与「规则本身写错了」。 */
function classify(error) {
  const code = error && error.code;
  if (code === 'ERR_SCRIPT_EXECUTION_TIMEOUT') {
    return 'timeout';
  }
  if (error instanceof SyntaxError) {
    return 'syntax';
  }
  return 'runtime';
}

function handleEval(params) {
  const code = params.code;
  if (typeof code !== 'string' || code.length === 0) {
    return { ok: false, error: { kind: 'invalid_params', message: '缺少 code' } };
  }

  const timeout = Number(params.timeout) > 0 ? Number(params.timeout) : 15000;
  const globals = { ...(params.vars ?? {}) };
  globals.java = createJavaApi({
    hostRequest,
    log: (text) => writeLog(text)
  });

  try {
    const result = runInSandbox(code, globals, timeout);
    return { ok: true, result: normalize(result) };
  } catch (error) {
    const message = error && error.message ? String(error.message) : String(error);
    if (classify(error) === 'timeout') {
      writeLog(`规则执行超时（${timeout}ms）`);
    }
    return { ok: false, error: { kind: classify(error), message } };
  }
}

function main() {
  writeLog(`sidecar 就绪 node=${process.version} pid=${process.pid}`);

  while (true) {
    const line = readLineSync();
    if (line === null) {
      writeLog('stdin 已关闭，退出');
      break;
    }
    if (line.trim() === '') {
      continue;
    }

    let message;
    try {
      message = JSON.parse(line);
    } catch {
      writeLog(`忽略无法解析的输入行：${line.slice(0, 200)}`);
      continue;
    }

    if (message.method === 'ping') {
      writeMessage({ id: message.id, ok: true, result: 'pong' });
      continue;
    }

    if (message.method === 'shutdown') {
      writeMessage({ id: message.id, ok: true, result: null });
      break;
    }

    if (message.method === 'eval') {
      writeMessage({ id: message.id, ...handleEval(message.params ?? {}) });
      continue;
    }

    writeMessage({
      id: message.id,
      ok: false,
      error: { kind: 'unknown_method', message: `未知方法：${String(message.method)}` }
    });
  }
}

main();
