/**
 * JS 规则沙箱。
 *
 * ## 安全边界在哪里（重要，别搞错）
 *
 * **`node:vm` 不是安全边界。** 它隔离的是全局变量与作用域，不是权限 ——
 * 通过 `someHostFunction.constructor` 一类的路径，构造器链可以摸到宿主
 * 的 `Function`，进而拿到宿主的 `process`。这是 vm 的已知性质，不是 bug，
 * 官方文档也这么写。
 *
 * **真正的边界是「独立进程 + 不注入危险 API」**：
 *
 * - sidecar 是独立进程，崩了、卡了、跑飞了都影响不到 Python 主进程
 * - 进程里没有数据库、没有 token、没有任何凭据 —— 逃逸出去也没东西可拿
 * - 内存由 `--max-old-space-size` 在进程级限制，超时由 vm 兜住
 * - 网络只能走 `java.ajax` 回调 Python，因此 SSRF 防护与限速仍然生效
 *
 * 所以这里的 vm 只负责两件事：**隔离全局变量**（书源之间不串味）与
 * **执行超时**（死循环能被打断）。不要把它当权限沙箱用。
 */

import vm from 'node:vm';

/**
 * 在沙箱里执行一段 JS，返回它的完成值。
 *
 * Legado 的规则体就是一段脚本，取**最后一条语句的值**作为结果 ——
 * `vm.Script` 的返回值正好是这个语义，所以不需要包一层函数。
 *
 * @param {string} code 规则代码。
 * @param {Record<string, unknown>} globals 注入沙箱的全局变量。
 * @param {number} timeoutMs 执行超时（毫秒）。
 * @returns {unknown} 代码的完成值。
 */
export function runInSandbox(code, globals, timeoutMs) {
  const context = vm.createContext(globals, {
    name: 'legado-rule',
    // 书源里 eval / new Function 是常见写法，禁掉会误伤大量规则。
    // 允许它们并不会突破进程边界 —— 上面说了，vm 本来就不是权限边界。
    codeGeneration: { strings: true, wasm: false }
  });

  const script = new vm.Script(code, { filename: 'legado-rule.js' });
  return script.runInContext(context, { timeout: timeoutMs });
}
