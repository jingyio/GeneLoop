# 结构化素材读取与真实复用对照

2026-10-30 新入口：从正常模型轨迹学习参数化 TSX 程序，并对**复用形式本身**做外环 RSI，详见[新实验记录](../../../docs/experiments/remotion-program-rsi-20261030-v1.md)。下面的只读参数边实验保留为历史对照。新入口仍在同一 Remotion 沙箱实际生成视频，不复用旧成片。

程序学习使用 `learn_programs.py --run <正常成功运行目录> --output <新目录> --call-model`；`certify_programs.py --library <候选库> --output <新目录>`用实际渲染检查选定来源帧。正常调用中新写出的源码也可来自程序臂的回退/修复，仍须有当前源码全文调用与同一视频收据，程序重放不能自证。当前任务仍由模型选择程序和当前参数。Python负责编译，`src/adapters/source_program_runtime.ts`校验和实例化；场景服务负责已有写入和渲染权限。

同一个已学库可以表示为 `program_catalog`（目录+通用调用）或 `typed_tools`（由学出的参数schema自动生成具体MCP工具），后者可以用程序描述自动命名。它们共用同一程序与渲染器；普通基线也有 `render_source(text)`，从而区分程序学习收益与普通工具融合收益。普通基线实际注册8个原生工具，目录形式增加2个接口，类型化形式只增加学习库工具，不再注册重复目录API；四程序库时分别8/10/12项。

外环按如下顺序运行，付费步骤仍须满足本实验的已有授权、同一个累计账本和有限阶段调用约束：

```sh
# 1. 根据已有测量提议形式，只生成候选，不发布。
node scripts/project.mjs python scripts/propose-reuse-form.py --measurements "$REPORT" --store "$STORE" --owner "$OWNER" --output "$PROPOSAL_DIR" --call-model
# 2. 在运行前冻结的新题面上做完整配对；默认没有--call-model只预览。
node scripts/project.mjs python scenarios/remotion_edit/structured/run_trial.py --phase evaluate --trial "$ROUND" --tasks "$TASKS" --output-root "$STUDY" --program-library "$LIBRARY" --form-file "$PROPOSAL_DIR/proposal.json" --call-model
node scripts/project.mjs python scenarios/remotion_edit/structured/verify_runs.py --output-root "$STUDY" --trial "$ROUND"
# 独立模型只引用原Agent已经上传的本实验图片ID，不新增上传；审阅范围限于抽帧。
node scripts/project.mjs python scenarios/remotion_edit/structured/review_program_runs.py --output-root "$STUDY" --trial "$ROUND" --call-model
node scripts/project.mjs python scenarios/remotion_edit/structured/analyze_programs.py --output-root "$STUDY" --trial "$ROUND" --tasks "$TASKS"
# 3. 费用至少下降20%、无新增所测质量失败、确有程序执行才晋级；拒绝也留记录。
node scripts/project.mjs python scripts/reuse-form-rsi.py --store "$STORE" --owner "$OWNER" --proposal "$PROPOSAL_DIR/proposal.json" --measurements "$STUDY/analysis-$ROUND/summary.json" --library "$LIBRARY" --publish
```

发布后，后继 `run_trial.py` 使用 `--form-store "$STORE" --form-owner "$OWNER"`固定本任务策略及库；`learn_programs.py`用相同参数将已发布的 `compiler_instruction` 输入下一次真实编译，并保存父策略摘要。下一轮反思再次读取这些实际结果和当前父策略。门槛、权限和评估器不属于模型可修改的形式字段。没有合格候选时不移动latest，也不把单元测试当作实际晋级。

后继认证的新程序与已发布库合成新的候选池，保留库的父摘要/代次；下一次形式反思读取这个新池，当前任务仍固定已发布库。此成功递归分支目前尚未实测。本轮程序复用已观察到六题全部采用、44→30请求和35.8%前向代理费下降，但原质量门槛拒绝，已停止新增批次；完整边界见实验报告文首。

可选`review_mode=external_selected_frames`和`review_protocol=<文件>`在新任务前固定原始像素复核协议。缺少记录时返回`awaiting_external_pixel_reviews`，同一计划补齐后续接；记录绑定当前任务、视频及协议摘要。`post_publication`可配置相同两字段。该模式仅完成实现和局部回归，尚未实测晋级；不能将其称为已验证的无人值守评审。

也可用 `evolve_forms.py --plan <私有冻结plan.json> --call-model`执行一整轮有限搜索。plan明确store/owner、output_root、library、tasks、baseline_trial、候选name/trial/proposal及逐任务schedule；未加`--call-model`仅显示计划。该入口调用上面的原有Harness、检查与记账入口，保留所有失败，再按既定门槛选择合格候选中费用最低的一项。`scripts/reuse-form-rsi.py --expand <新目录>`可枚举有限接口变体；未实际测量的变体不是结果。

共享普通基线时，`analyze_programs.py --baseline-trial <基线trial>`引用同一批真实运行。默认候选形式策略只作用于program臂；相同源码渲染能力保持可用。必须报告物理运行数及共享关系，不能把一批基线重复当成独立样本。`parameter_binding=defaults`只合并顶层默认值，数组与对象整项替换，合并后的完整参数仍按同一schema校验；不从历史默认值推断当前任务的语义选择。

当plan指定`baseline_form`时，会先核对各候选共用同一Agent指令，再让基线与程序臂共同使用该指令，单独比较可执行复用表示。`program_evidence=source`把实际实现源码作为能力证据，支持模型核对循环/分支与参数范围；默认interface只显示描述、schema和例子。描述中的历史示例次数不自动成为代码的执行上限。

`library_scope=all`保留全库接口，`lexical_top1`以当前任务和学出描述/参数名做通用词项检索，只展示一项；无词项重合时保留全库。普通生成工具不变，模型仍负责适用性与当前绑定。选择器位于TS运行时，Python和MCP共用，快照记录实际可见ID。四程序库在类型化模式下，普通基线8工具、全库12工具、检索到一项时9工具。展示范围缩小可能影响缓存或漏掉合适程序，须由独立任务的实际总费用/质量决定，不能凭上下文长度宣称收益。

plan可带`post_publication: {"tasks":"<预先冻结的新任务JSON>","trial_prefix":"published-followup"}`。晋级后`continue_form.py`自动运行新任务对照、核验真实策略加载，再让正常源轨迹消费已发布的编译指令，来源认证后生成下一轮形式提案；新候选仍等待下一轮独立验证。也可显式调用该入口接续一个已发布轮次。入口要求Node22.18+的原生TypeScript剥离；当前服务器实测Node22.23.3、Python3.10.21，未验证其他平台。

以下是[30题motivation](../../../docs/experiments/remotion-motivation-20261027-v2.md)之后的历史参数边实验入口。该路线只认证`pin_asset(name)→probe_media(source_id)`；模型仍选择素材、编写React、决定剪辑并审阅真实图片。写源码、渲染和保存笔记都不作为只读参数边Motif；上面的程序路线独立支持当前工作区源码生成和实际渲染。

四臂是legacy旧4工具、typed结构化工具、execute同工具加认证库，以及fused普通直接`probe_asset(name)`工具。工具化变化与Motif边际效果分开；fused用于防止把一个简单融合操作的收益过度解释为架构优势。题面、划分、顺序和窄QA时点在tasks.json，公共只读契约在contracts.json。

需要先准备父目录README所述私有Remotion环境与素材。以下入口要求已有累计ledger/checkpoint，不创建新的零预算历史。仅用于已有明确真实实验与无费用上限授权的生成工作区。

```sh
source .local/remote-env.sh
export REMOTION_EXPERIMENT_ROOT="$PWD/.local/experiments/remotion-motivation-20261027-v1"
# REMOTION_IMAGE使用已经无模型验证的不可变镜像；凭证仅在私有环境提供。
node scripts/project.mjs python scenarios/remotion_edit/structured/preflight.py
node scripts/project.mjs python scenarios/remotion_edit/structured/run_trial.py --phase learn
# 免费预览、授权和预检通过后添加--call-model，执行2train+1cert普通任务。
node scripts/project.mjs python scenarios/remotion_edit/structured/run_trial.py --phase learn --call-model
node scripts/project.mjs python scenarios/remotion_edit/structured/verify_runs.py
node scripts/project.mjs python scenarios/remotion_edit/structured/learn.py
node scripts/project.mjs python scenarios/remotion_edit/structured/run_trial.py --phase evaluate
node scenarios/remotion_edit/structured/verify_library.mjs
# 上述通过后，才执行真实四臂评测。
node scripts/project.mjs python scenarios/remotion_edit/structured/run_trial.py --phase evaluate --call-model
node scripts/project.mjs python scenarios/remotion_edit/structured/verify_runs.py
node scripts/project.mjs python scenarios/remotion_edit/structured/preserve_previews.py
node scripts/project.mjs python scenarios/remotion_edit/structured/analyze_runs.py
```

同一个累计账本同时只能有一个runner。`result.json`存在就保留，不删除失败重跑；修订使用新trial和有效配置。`learn.py`拒绝覆盖已有库，输入身份/事件/源码摘要与独立认证不能靠重算哈希跳过。

输出在私有`structured-v1/runs/<trial>/<arm>/<task>/`；内部下一层同名task目录是真实模型工作区。`effective.json`保存实际提示/工具顺序/源SHA/代码/库配置，`events.jsonl`和结果在工作区之外。模型真实在线审计在工作区`.local/online-motif`；合成协议诊断在独立diagnostics，不能混算。

模型推理行有request_id与usage；Files API传输行没有request_id，必须单列，不能当成丢失模型记录或删去。估费不是账单实付；缓存、重试、失败、种子学习与维护成本都要区分。源码摘要明确只覆盖entry文件，不保证任意JS依赖；没有基础插件脱离Python或Windows支持的结论。

`verify_runs.py`执行尺寸/fps/帧数/全解码和固定源帧、静音窗口检查；不代替完整质量盲评。`preserve_previews.py`只把严格SHA一致的像素记为保全；重提图片不是新任务。当前结果、失败和限制见[协议及实验记录](../../../docs/experiments/remotion-structured-reuse-20261028-v1.md)。

v1出现源裁剪语义错误后，另冻结了[共同语义交接复验](../../../docs/experiments/remotion-structured-reuse-20261028-v2.md)。`tasks-v2.json`含两个同题复测和三个新参数变体；三个结构化臂使用相同核对提示，保留原库和原失败。v1结束并封存账本后，使用新代码快照串行运行：

```sh
node scripts/project.mjs python scenarios/remotion_edit/structured/run_trial.py --trial v2 --tasks scenarios/remotion_edit/structured/tasks-v2.json --phase evaluate
# 完成免费preview和既有库守卫核验后，同一命令添加--call-model。
node scripts/project.mjs python scenarios/remotion_edit/structured/verify_runs.py --trial v2
node scripts/project.mjs python scenarios/remotion_edit/structured/preserve_previews.py
node scripts/project.mjs python scenarios/remotion_edit/structured/analyze_runs.py --primary-trial v2 --training-trial v1 --tasks scenarios/remotion_edit/structured/tasks-v2.json
```

v2分析写`analysis-v2/summary.json`，沿用v1三条种子的完整学习成本。`qa/semantic-review.json`可保存有范围说明的Agent抽帧审阅与已发现错误；它不会把技术门槛通过变成人工盲评通过。

当前源码还包含[错误反馈修复与单题局部恢复](../../../docs/experiments/remotion-structured-reuse-20261028-recovery-v3.md)：已知拒绝／媒体失败通过MCP `ToolError`保留有界原因；不降低版本守卫。**旧认证库会拒绝变更后的server源码**，v1/v2实测仍使用其冻结导出。新代码不能套改旧manifest hash执行，后续execute须重新认证。本次局部恢复只用typed baseline，不计新独立任务或Motif收益。

两轮矩阵完整同步本地后，可用`prepare_blind_review.py`生成去臂标签的35条审阅包，包括未交付条目；`ratings.json`初始全为null，私有映射在包外。它准备材料，不执行或冒称人工盲评。脚本拒绝覆盖已有评分包。
