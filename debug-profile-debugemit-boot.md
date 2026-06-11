[OPEN]

# Debug Session: profile-debugemit-boot

## Symptoms
- 页面停留在“页面加载中… 若长时间停留在此，请检查网络是否可访问 CDN 资源。”
- 浏览器报错：`Uncaught ReferenceError: debugEmit is not defined`
- React / ReactDOM / Babel 资源均已加载成功，但页面应用未完成启动。

## Scope
- 人物页前端模板：`storymap/script/templates/profile_page.html`
- 重新生成后的产物页：`artifacts/story_map/*.html`

## Falsifiable Hypotheses
1. `debugEmit` 定义没有进入最终执行上下文，导致后续顶层调用直接抛错。
2. 某个新插入的顶层调用在 `debugEmit` 定义之前执行，触发启动即崩溃。
3. 模板页和生成产物页不一致，模板有定义而产物缺失。
4. Babel 自动编译/补编译流程重复执行，改变了脚本求值顺序。

## Evidence Plan
- 读取模板与产物中的 `debugEmit` 定义位置和首次调用位置。
- 若静态顺序不足以解释，则添加最小化运行时上报，采集脚本启动顺序。
- 修复后对比 `pre-fix` / `post-fix` 页面启动行为。
