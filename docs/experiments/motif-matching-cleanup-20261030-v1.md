# Motif 匹配与参数编译第一轮清理

- 更新时间：2026-10-30，Codex。
- 范围：用户要求减少重复校验与人工场景规则；本轮优先删除可以明确定位的重复实现和无效配置，不新增自动写入权限或场景策略。
- 基线：远程 main `ec72908755ea6df1771ec962b40e3b27be381ebb`；隔离分支 `codex/simplify-motif-parameter-evidence`，原 Desktop 工作区保留。

## 前文结论

- 以已观察到 Token 降低的 Paper/BibTeX Script Motif 为主要阅读实例；它与通用 MCP 参数边编译器是不同学习路径，不能混用实验结果。
- 参数边编译和 Script 结构编译均由确定性程序完成；可选的模型描述更新不接收整条轨迹，也不重写执行代码。
- 候选发现、结构认证、在线选择、实际执行和整任务质量分别陈述，不把同一层检查重复包装成多份独立证据。
- 只读、固定第一页及工具名字特判是当前实现范围，不是 Motif 定义；通用方法应将学习到的参数流与当前任务的读写权限分开。
- 优先删除重复实现与无效配置。资料是否变化、调用是否失败等真实证据仍需由公共执行层负责，不以继续增加场景白名单替代学习。

## 问题与改动

1. `proposeNext()` 在仓库生产代码中没有调用者，却独立维护连续前缀与分差选择算法。现保留函数入口，委托现用的 `proposeReadyBatch(maxBatch=1)`；单个和批次建议共享参数绑定、版本、歧义与屏障规则。旧辅助入口现在也支持已观察的来源锚点和交错历史，不再保留独立的 margin 选择语义。
2. 会话拦截器在每条历史中写入相同的 `task.input_version`，随后与同一个任务值比较。删除历史标签及重复比较。任务自身的 `input_version`、会话隔离、实际来源版本及授权协议不变；外部调用匹配辅助函数时，应传入该任务自己的历史。
3. 批次匹配没有使用 `minMargin` 做候选选择。删除该形参、验证、传递和通用插件的 `SSS_MOTIF_MIN_MARGIN` 读取。Script Motif 自己的分差阈值与配置不在本次范围内。
4. 保留上一轮已完成的删除：参数边与序列编译器不再要求训练值至少两种，仍核对来源与参数关系。复用当前值，不固化训练常量。
5. File 公共种子的历史源码快照只作来源记录，不再作为安装的一票否决条件；删除安装前的整图快照比较与认证入口的重复比较，仍实际核对 `policy_current()` 中的当前工具契约、图绑定与执行版本。TypeScript 同步删除历史快照与当前注册表快照的相等比较，保留当前注册表源码绑定、证书载荷及独立见证检查；实际接管仍核对当前任务的工具契约、执行版本和权限。File v16 四图通过当前语义兼容检查，v5/v7 仍因真实接口/执行差异被拒绝，旧证书与载荷不改写。

## 兼容库

使用已有 `scripts/reexport-native-capabilities-compat.py` 的审阅、重导出和分阶段发布函数，生成新目录 `paper-web-v33` / `ppt-master-v30`，旧目录不改写。配置入口为本 worktree 私有 `.local/reexport-matching-cleanup.py`。

Paper 允许的源码差异恰为 `dsh_online_motif.mjs`、`online_skill_runtime.mjs`、`edge_compiler.py`、`trace_compiler.py`；PPT 恰为前两个。要求旧包摘要有效、用当前导出器重导出的 manifest 完全一致、IR/manifest/task/schema/来源证据逐字节不变，再核验新包实际可加载。新报告保留旧报告并追加 `matching_cleanup_compatibility`；不以直接编辑旧哈希代替验证。

这是旧程序在新匹配实现下的兼容验证，原始轨迹重放、新训练任务和模型请求均为 0，不宣称重新完成独立训练认证、质量晋级或效果实验。编译器来源锁与在线依赖锁的进一步拆分留待后续，不在加载器里忽略旧证书。

File 原始分发包继续使用已有 `config/file-management-runtime-compatibility.json` 绑定当前公共验证器；更新这一独立兼容记录，原 catalog 与 15 份原始载荷逐字节保留，不生成新执行证书或自动激活证明。来源快照相同不能替代工具契约检查；来源快照不同也不直接证明工具执行语义已变化。

## 验证与限制

- 在线匹配及授权续接定向：43 项通过；新增断言证明单建议与批次建议在观察锚点下返回同一结果，历史不依赖人工输入标签。
- 参数编译与真实产品包/场景加载集成定向：71 项通过。
- File 种子和原始分发包：23 项通过；执行版本/当前 catalog 改变会拒绝的两个回归均通过。最终 TypeScript 对齐后，再跑 File Python 种子 17 项通过。
- 基线反例：原样 main 快照中，两项 `test_scene_file_delivery.py` 的 PDF 导出测试同样失败；日志 `.local/cleanup-baseline-delivery.log`。不归因于本次清理，也不修改断言掩盖。
- 全量 Python：1519 通过、235 跳过、2 失败；失败即上述原样 main 已复现的 PDF 交付问题，日志 `.local/cleanup-npm-test-final.log`。`npm test` 在 Python 失败后退出，因此另行运行全部 Node 测试，不把未执行的阶段算作通过。
- 全量 Node：1375 通过、15 跳过、1 失败；两次全量均为 `test_model_transport_gateway.mjs` 的 `oversized upload already in flight still receives typed 413` 报 `write ECONNRESET`。原样 main 在相同环境和完整并发运行下亦为 1375/15/1，失败测试、错误及位置一致；候选与 main 单独运行该文件均通过。保留 `.local/cleanup-node-full-final.log`、`.local/cleanup-node-full-before-retry.log`、`.local/cleanup-baseline-node-full.log` 及两侧定向日志，未修改网络实现或测试断言。
- `npm run smoke`、`npm run motif:check` 均通过，都是无模型诊断。新 Paper/PPT 库加载与文件摘要核对通过；旧 Paper/PPT 库、File v16 及原始 File 分发载荷保持不变。
- 未运行付费模型或修改正式服务；原 Paper 的 Token 效果结果没有重测，不能宣称本轮提高覆盖率或节省比例。
- 没有发现新增回归，但全量仍有上述三个已对照复现的基线失败，不能表述为全量通过。早期非标准 Python/临时路径环境下的失败日志亦保留，不用重跑结果覆盖。
- 生产 `src/` 源码最终 diff 为增加 11 行、删除 82 行，净减少 71 行；不把测试、文档或兼容数据量混入该数字。

## 后续范围

下一轮再处理工具名字特判、固定第一页、广泛失效屏障，以及候选发现与自动执行权限的分离。它们会改变接管行为，不能把直接删掉一处判断称为已支持通用写入。本轮不增加替代白名单、开关或新的 Agent 循环。
