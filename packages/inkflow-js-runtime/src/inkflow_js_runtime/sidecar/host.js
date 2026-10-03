/**
 * Legado 兼容的宿主 API。
 *
 * 分两类：
 *
 * - **纯计算**（base64 / md5 / hex / 时间）在本进程内完成。
 * - **网络**（ajax / get / post）必须**回调 Python** —— 请求只能由 Python 发出，
 *   才能复用它的 SSRF 防护、协议白名单与限速。让 sidecar 自己发请求等于
 *   在安全模型上开了个洞。
 */

import { createHash } from 'node:crypto';

/**
 * 创建 `java` 对象。
 *
 * @param {(payload: object) => object} hostRequest 同步回调 Python 的桥；
 *   由 main.js 提供（它知道怎么写协议、怎么等响应）。
 * @param {(text: string) => void} log 日志出口。
 */
export function createJavaApi({ hostRequest, log }) {
  /** 把 Python 的响应转成 Legado 期望的形态。 */
  const fetchLike = (method, url, body, headers) => {
    const response = hostRequest({
      url: String(url),
      method,
      body: body === undefined || body === null ? null : String(body),
      headers: headers ?? null
    });

    if (!response || response.ok !== true) {
      const message = response && response.error ? response.error : '请求失败';
      throw new Error(`java.ajax 失败：${message}`);
    }

    const content = response.body ?? '';
    // Legado 的 java.ajax 直接返回响应体字符串
    return content;
  };

  return {
    // ---------------------------------------------------------------- 网络

    /** Legado：`java.ajax(url)` —— 同步返回响应体。 */
    ajax(url) {
      return fetchLike('GET', url);
    },

    get(url, headers) {
      return fetchLike('GET', url, null, headers);
    },

    post(url, body, headers) {
      return fetchLike('POST', url, body, headers);
    },

    // ---------------------------------------------------------------- 编码

    base64Encode(text) {
      return Buffer.from(String(text), 'utf8').toString('base64');
    },

    base64Decode(text) {
      return Buffer.from(String(text), 'base64').toString('utf8');
    },

    /** 32 位小写 MD5。 */
    md5Encode(text) {
      return createHash('md5').update(String(text), 'utf8').digest('hex');
    },

    /** 16 位 MD5（取 32 位结果的中间 16 位）。 */
    md5Encode16(text) {
      return createHash('md5').update(String(text), 'utf8').digest('hex').slice(8, 24);
    },

    digestHex(algorithm, text) {
      const name = String(algorithm).toLowerCase().replace('-', '');
      return createHash(name).update(String(text), 'utf8').digest('hex');
    },

    hexEncodeToString(text) {
      return Buffer.from(String(text), 'utf8').toString('hex');
    },

    hexDecodeToString(hex) {
      return Buffer.from(String(hex), 'hex').toString('utf8');
    },

    // ---------------------------------------------------------------- 其它

    /** Legado 的 `java.timeFormat`：毫秒时间戳 → `yyyy-MM-dd HH:mm:ss`。 */
    timeFormat(timestamp) {
      const date = new Date(Number(timestamp));
      const pad = (value) => String(value).padStart(2, '0');
      return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
        `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
      );
    },

    log(message) {
      log(String(message));
    },

    toast(message) {
      log(`[toast] ${String(message)}`);
    }
  };
}
