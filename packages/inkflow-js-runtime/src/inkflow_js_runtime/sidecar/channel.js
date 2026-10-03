/**
 * 同步 stdio 通道。
 *
 * **为什么是同步的。** Legado 的 JS 规则里 `java.ajax(url)` 是**同步**调用 ——
 * 书源代码不会写 `await`（它是给 Rhino 写的）。所以执行期间必须能阻塞等待
 * Python 的响应。
 *
 * 做法是 `fs.readSync(0, ...)`：stdin 是管道时它会阻塞到有数据为止。
 * 因为 Python 是独立进程，阻塞期间它能正常处理请求并发回响应，不会死锁。
 * 用 worker + Atomics 也能实现，但没必要 —— 单线程更简单，也更好排查。
 *
 * **stdout 只用于协议。** 日志一律走 stderr，否则会把 JSON 行冲乱。
 */

import fs from 'node:fs';

const READ_CHUNK = 64 * 1024;

let pending = '';
let eof = false;

/** 写一行 JSON 到 stdout（协议通道）。 */
export function writeMessage(message) {
  fs.writeSync(1, `${JSON.stringify(message)}\n`);
}

/** 写一行日志到 stderr（不参与协议）。 */
export function writeLog(text) {
  fs.writeSync(2, `[sidecar] ${text}\n`);
}

/**
 * 同步读一行。
 *
 * @returns {string|null} 读到的一行（不含换行）；stdin 关闭时返回 null。
 */
export function readLineSync() {
  while (true) {
    const index = pending.indexOf('\n');
    if (index >= 0) {
      const line = pending.slice(0, index);
      pending = pending.slice(index + 1);
      return line;
    }

    if (eof) {
      // 末尾没有换行的最后一行
      const rest = pending;
      pending = '';
      return rest.length > 0 ? rest : null;
    }

    const chunk = Buffer.allocUnsafe(READ_CHUNK);
    let read = 0;
    try {
      read = fs.readSync(0, chunk, 0, READ_CHUNK, null);
    } catch (error) {
      // EAGAIN：管道暂时没数据。等一下重试，不当成致命错误。
      if (error && error.code === 'EAGAIN') {
        continue;
      }
      throw error;
    }

    if (read === 0) {
      eof = true;
      continue;
    }

    pending += chunk.subarray(0, read).toString('utf8');
  }
}
