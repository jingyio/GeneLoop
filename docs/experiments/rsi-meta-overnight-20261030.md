# RSI 共享质量证据与视频形式递归验证

状态：实现与本地集成检查完成，V100 六对新任务真实验证进行中。发布、后继采用和下一轮学习结果以收尾记录为准。

## 问题与假设

F02 的通用协议/优化代码在 PR115 中合入 F00 工作分支，未进入主线；视频形式外环使用自己的更新记录。另有两类实际缺口：抽帧模型评审会误判，无法仅凭 accepted 作为真实质量；发布后的学习器可能吸收已被质量评审拒绝的正常源码。

本轮在远程 main `26033884e8393b9e3aa6365801950710bf6f7cfd` 上恢复 F02，并将复用形式更新和逐项质量证据接入共享协议。目标是让一次真实合格的形式更新被后继任务消费，继续产生带父版本的编译结果与下一形式候选。若新任务不满足质量或至少20%前向模型费用下降，保留拒绝；测试通过本身不支持效果结论。

## 实现

- `quality_evaluation` 统一绑定任务、最终产物、评价标准，以及检查项的 passed/failed/unknown、具体观察、证据路径与SHA。Python/TypeScript解释一致，宿主验证实际证据文件。
- F02 候选协议增加可选 `reuse_form` 版本与 `reuse_form_revision`，旧 Motif/Matcher 记录仍有效。`reuse_form_protocol.py` 把已验证形式报告适配为共同候选/验证记录，调用 TypeScript `validateRsiUpdate`；现有不可变代次与原子 latest 指针发布共同回执。新任务的 Python/TS 加载器核对共同回执。
- 视频场景保留解码、源帧、当前源码和音窗检查；原尺寸选定帧以隐藏臂名/费用的包复核。共同格式不证明评价本身正确，仍以实际观察和所声明的有限范围为依据。
- 下一次编译仅吸收质量通过且确由模型 write_source/render_source 产生的当前源码。普通程序回放不能作为自身新训练证据；无合格源码明确暂停学习。下一反思看到新认证候选池，下一代仍需另行留出验证。

## 任务与对照

本轮为公开影片的技术参数变体，不能称为六位真实客户或跨领域任务。新验证题为 `tasks-meta-validation-v7.json` 的 t86–91：三镜头、四镜头、两项不同窗口的画中画、音频窗口和较小数据面板。初始12次物理运行为同题普通融合/程序两臂，交替顺序；共用原生8工具，候选另暴露4个学出程序。普通融合也可直接 render_source，避免将工具融合收益归因于学习。

候选为上一轮真实 Meta007 提出的 typed/source/all 形式，不根据本轮结果人工更改。源库v7保留v6的三程序，用实际请求3096产生且三处来源帧MAE均0的面板修复替换旧面板。来源认证只证明选定来源画面等价，不证明新任务泛化。

若候选合格发布，预先固定的 `tasks-published-policy-v2.json` t92/t93 运行新任务并由 TypeScript 读取发布策略，再从合格正常源码继续真实学习、认证与反思。只有实际回执能支持这些阶段完成。

## 配置与复现

- 服务器：V100 `/home/jingyij/jjy`，项目隔离环境，先加载 `.local/remote-env.sh`。不切换/重启正式服务。
- 模型：deepseek-flash，thinking disabled / reasoning_effort off；任务和编译单次输出6000，形式反思沿用2000。费用/请求数不限，`cap_usd:null`、`budget_policy:uncapped_user_authorized`、`reset_history:false`。单任务900秒诊断窗口，失败保留。
- BASE 为私有 `.local/experiments/remotion-motivation-20261027-v1/`，新增目录 `rsi-meta-overnight-20261030/` 保存授权、任务/协议/代码摘要、frozen-plan-v2、结果、共同发布回执；所有请求仍追加 BASE 既有 ledger/requests/checkpoint。
- 冻结代码v2 archive SHA256：`5cf4a72bf16701ba1bb7dcad6708053592575aa1cab117c3553336675de039bb`。此前v1仅免费预检，无模型调用；首个付费请求从3097开始。初始累计checkpoint3096、预约记账USD2.535614568不是账单。
- 新计划、原始帧协议、任务和源码清单的完整摘要在私有 `code-effective-v2.json` / `frozen-inputs-before-model.json` 与本地 `code-v2-manifest.json`，旧快照不覆盖。运行入口沿用 `evolve_forms.py --plan PLAN --call-model`；缺少独立像素记录暂停后，同计划续接跳过已完成任务。
- CODE2 `effective.core_baseline` 仍保留历史参数边实验的ec72908标识；本轮实际基线以上述main与冻结代码包为准，该旧字段不能当本轮commit。

## 验证

本地使用现有完整依赖环境。定向83 Python/41 Node通过；随后来源质量修订相关29项通过。完整Python1616通过、235跳过。正确Python PATH与规范化TMPDIR下Node1424通过、15跳过、1个既有typed413并发EPIPE失败；其所在文件单独9项通过。最初缺少fitz、沙箱拒绝监听/临时文件、macOS `/var` 与 `/private/var` 别名及硬编码python3的失败均保留日志，未改断言规避。

`npm run rsi:check`、`npm run smoke`、`npm run motif:check`通过，均为无模型诊断，不能当真实质量/费用效果。两版真实MCP预检均10项通过、零模型请求，共同原生schema/顺序一致。

## 结果、成本与限制

待收尾：实际任务、费用/用量、逐项质量、发布与后继父链。DeepSeek账本保留正常、失败、修复、学习、反思与历史未结算；未知费用保持null，账单实付未知。Codex宿主开发/复核用量费用未知，单列，不记为零。

本轮采用已有“合格前向模型费用”的晋级目标；F02优化器的冷研究净收益/未来摊销审核是另一目标，不能宣称本轮已摊回全部历史探索。AI选定帧复核不是人工盲评、全片视觉或完整音频验收，知道研究背景的同一编码聊天仍存在偏倚。共同协议和测试不证明开放领域自进化；候选表示空间仍有界，未修改通用Matcher算法或递归改写优化器代码。
