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
    // ---------------------------------------------------------------- 取值

    /**
     * Legado：`java.getString(rule)` —— 用**规则**从当前页面取值。
     *
     * 这里的「当前页面」是 Python 侧求值时的上下文（HTML 或 JSON）。
     * 规则求值的能力在 Python（lxml / JSONPath），所以这一趟要走反向 RPC，
     * 而不是在 sidecar 里重造一套。
     *
     * @param {string} rule 选择器或 JSONPath（支持 Legado 的 `!N` 下标等写法）。
     * @param {boolean} [isRule] Legado 的第二个参数，传 false 表示按字面量处理。
     */
    getString(rule, isRule) {
      const response = hostRequest({
        op: 'getString',
        rule: String(rule),
        isRule: isRule === undefined ? true : Boolean(isRule)
      });
      if (!response || response.ok !== true) {
        const message = response && response.error ? response.error : '取值失败';
        throw new Error(`java.getString 失败：${message}`);
      }
      return response.value ?? '';
    },

    // ------------------------------------------------------------ 书源变量

    /**
     * Legado：`java.put(key, value)` —— 存一个**书源级**变量。
     *
     * 生命周期跟着书源走，跨规则、跨请求都在 —— 书源常用它把 tocUrl
     * 里算出来的 bookId 传给 chapterUrl。返回值是写入的值，便于链式写。
     */
    put(key, value) {
      const text = value === undefined || value === null ? '' : String(value);
      hostRequest({ op: 'put', key: String(key), value: text });
      return text;
    },

    /** Legado：`java.get(key)` —— 取书源级变量。 */
    get(key) {
      const response = hostRequest({ op: 'get', key: String(key) });
      return response && response.value !== undefined && response.value !== null
        ? String(response.value)
        : '';
    },

    // ---------------------------------------------------------------- 网络

    /** Legado：`java.ajax(url)` —— 同步返回响应体（这就是 GET）。 */
    ajax(url) {
      return fetchLike('GET', url);
    },

    post(url, body, headers) {
      return fetchLike('POST', url, body, headers);
    },

    /**
     * Legado：`java.ajaxAll(urls)` —— 批量请求，返回数组。
     *
     * 每个元素有 `body()` 方法取响应体（Legado 的用法是
     * `java.ajaxAll(list).map(x => x.body())`）。
     *
     * **当前是串行实现的**：sidecar 是同步阻塞模型，一次只能等一条响应。
     * 语义与 Legado 一致，但没有并发收益。真实书源里这个 API 用得不多
     * （样本里 4 处），先保证正确。
     */
    ajaxAll(urls) {
      const list = Array.isArray(urls) ? urls : [urls];
      return list.map((url) => {
        const text = fetchLike('GET', url);
        return { body: () => text, url: String(url) };
      });
    },

    // ---------------------------------------------------------------- 其它

    /**
     * Legado：`java.toNumChapter(text)` —— 中文数字转阿拉伯数字。
     *
     * 书源用它把「第一千零二十四章」这类章节名转成可排序的数字。
     *
     * 算法分两段：`万` 结算一整段并累加，`十/百/千` 在当前段内累加。
     * 「十二」= 12（`十` 前面没有数字时按 1 算）。
     */
    toNumChapter(text) {
      const raw = String(text ?? '').trim();
      if (!raw) {
        return '';
      }
      if (/^-?\d+$/.test(raw)) {
        return Number(raw);
      }

      const digits = {
        零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4,
        五: 5, 六: 6, 七: 7, 八: 8, 九: 9
      };
      const units = { 十: 10, 百: 100, 千: 1000 };

      let total = 0; // 「万」之前已结算的部分
      let section = 0; // 当前段
      let current = 0; // 待结算的个位

      for (const char of raw) {
        if (char in digits) {
          current = digits[char];
          continue;
        }
        if (char === '万') {
          section = (section + current) * 10000;
          total += section;
          section = 0;
          current = 0;
          continue;
        }
        if (char in units) {
          section += (current || 1) * units[char];
          current = 0;
        }
      }

      const value = total + section + current;
      return value === 0 ? '' : value;
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
