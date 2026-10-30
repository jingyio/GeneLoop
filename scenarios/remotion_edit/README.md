# Remotion 视频剪辑 motivation 实验

基于 GeneLoop `ec72908755ea6df1771ec962b40e3b27be381ebb`，通过现有 DSH SDK、场景适配器和累计费用代理运行真实剪辑 Agent。没有另写模型 Agent 循环；本目录只提供隔离工作区 MCP、批次调度和离线分析。当前是独立实验入口，尚未接入正式网页菜单。

## 范围与输入

`tasks.json` 冻结十个不同剪辑题目。素材为 [Remotion 官方测试媒体](https://remotion.media/) 的 `video.mp4`、`video-10s.mp4`、`audio.mp3`，不是十个真实用户项目，也不是官方剪辑 benchmark。分辨率最高640×480、时长4–6秒，不能推及长视频、真实镜头选择、语音识别或商业剪辑质量。

MCP 只有 `list_files`、`read_file`、`write_file`、`run_command`。模型自行探测素材、编写 React、调用 Remotion 和检查结果。每条任务使用独立持久容器，工作区可写、原素材和依赖只读、网络关闭、无模型凭证。模型调用在 V100 宿主上的 GeneLoop/DSH 内执行。

## 复现

需要 Linux Docker、项目已安装的 Node 22 / Python SDK / MCP。实验实际验证的渲染镜像为 `frappe/erpnext:v16.34.2` 的本机不可变 ID，内部 Debian 12、Node24.20.0、Chromium152；镜像引用不是可移植安装保证。其他镜像须包含 `/bin/sh`、Node 和 `/usr/bin/chromium-headless-shell`，另做无模型渲染核验。V100 宿主 glibc2.28 不能直接运行本轮 Remotion 原生渲染组件。

在项目根设置私有环境，不在命令中写入密钥字面值：

```sh
source .local/remote-env.sh
export REMOTION_EXPERIMENT_ROOT="$PWD/.local/experiments/remotion-motivation-20261027-v1"
export REMOTION_IMAGE="$(docker image inspect frappe/erpnext:v16.34.2 --format '{{.Id}}')"
# DEEPSEEK_API_KEY 由现有私有凭证环境提供，禁止打印。
mkdir -p "$REMOTION_EXPERIMENT_ROOT/runtime" "$REMOTION_EXPERIMENT_ROOT/assets"
```

在 runtime 目录通过 npm 固定安装：`remotion`、`@remotion/cli`、`@remotion/renderer`、`@remotion/bundler`、`@remotion/transitions` 均为 `4.0.539`，`react` 与 `react-dom` 均为 `19.1.0`；保留 npm lock。把三个官方原文件放入 assets 并保存来源、字节数与 SHA256。V100 直接下载曾返回403，本轮从本地官方源下载后按字节同步，未伪造媒体。

```sh
node scripts/project.mjs python scenarios/remotion_edit/run_study.py --parallel 2
# 上一条仅免费预览。确认本次运行授权后：
node scripts/project.mjs python scenarios/remotion_edit/run_study.py --parallel 2 --call-model
node scripts/project.mjs python scenarios/remotion_edit/analyze.py
```

`cap_usd=null`、请求数不限、单次输出6000 token，继续累计 checkpoint / ledger，不清历史。**该入口不设费用硬上限**，仅供已有明确无上限实验授权的隔离运行，不能代替公共产品的预算默认值。v3 收集器按原始 `turn/end` 结束本次收集，不改上游 Harness；单任务900秒检查点用于终止无进展诊断，仍保留费用和原事件，不是费用上限。

`results/<task>.json` 存在时不会重跑；不能删除失败结果重测。恢复应使用新目录或明确留档的 recovery trial。正常退出后检查本实验标签容器已清理；异常退出只清理 `geneloop.experiment=remotion-motivation-20261027-v1` 的本实验容器。

## 独立验收与结论边界

`verify.py` 核验真实视频流的尺寸、fps、解码帧数、完整解码并抽帧。它使用独立 `qa-runtime/node_modules/@ffmpeg-installer/linux-x64` 4.1.0 的完整 FFmpeg；Remotion 自带 FFmpeg 缺少本轮检查需要的部分编码器。第一批QA依赖不进入模型运行环境；第二批显式通过`--media-tools`开放完整FFmpeg，见下节条件变化。容器镜像 ID 从每任务有效配置读取。

```sh
node scripts/project.mjs python scenarios/remotion_edit/verify.py
```

媒体检查通过不代表题意、时序、视觉或音频质量通过。`completed` 只是模型会话结束；必须另查 `video_exists` 和独立 QA。审片与人工盲评分列，不能把已有黑屏、位置错误或提前放弃删去。

离线分析只从冻结训练组中的正常交付轨迹抽取候选；失败训练任务排除。前四题为训练候选，第5–6题为认证，第7–10题保留评测。调用现有 `extract_dsh_trace` 与 `build_read_motif_library`，通用 shell / 写文件仍为屏障，不能把 `ffprobe` 或渲染命令字符串擅自标为只读。无认证 library 时不启用 execute；工具名重复、纯工具响应或脚本重复均不是实际跳过模型请求。

当前结果和失败见 [实验记录](../../docs/experiments/remotion-motivation-20261027-v1.md)，接手入口见 [场景交接](../../docs/handoffs/remotion-edit.md)。原始日志、请求、源码、视频、账本均留在忽略的 `.local/`。

## 扩展到30题（第二批20题）

`tasks-v2.json`固定新增第11–30题；`tasks-all.json`只是30题注册表，不能拿它重跑或覆盖第一批。`split-v2.json`在新增调用前冻结：10题训练候选、5题认证、5题评测；旧10题仅作历史描述。

新增输入为官方示例《Big Buck Bunny》的三个不同12秒片段（24/30/60fps、640×360）和绿幕公共夹具。它们是同一影片的派生素材，来源与本次实际SHA见`assets-v2-sources.json`，不称独立拍摄任务。完整FFmpeg对模型工具开放、准确工具名/参数范围、日志移出工作区及单位提示均为第二批显式条件变化；前后费用差不构成Motif收益。

安装版4.0.539的`trimBefore/startFrom`使用**合成fps**换算秒数；`Sequence.from`控制输出时间轴。第一批题面曾误写为源fps，源/输出当时均30fps；旧原始提示不追改。第二批前已用30fps源、24fps合成实际抽帧验证：`trimBefore=24`对应源第1秒，而非1.25秒。代码和[官方说明](https://www.remotion.dev/docs/offthreadvideo)一致。

复现第二批时，先按上一节准备相同私有环境，保存已有账本与素材；获取父视频及绿幕原文件到`source-media-v2/`，使用`prepare_assets_v2.py`准备新派生素材。该脚本拒绝覆盖已有派生输出。实际运行的授权、父文件版本和前缀账本必须另存，不重置历史。

```sh
node scripts/project.mjs python scenarios/remotion_edit/run_study.py \
  --tasks scenarios/remotion_edit/tasks-v2.json --batch-id v2 \
  --asset-manifest "$REMOTION_EXPERIMENT_ROOT/asset-manifest-v2.json" \
  --media-tools "$REMOTION_EXPERIMENT_ROOT/qa-runtime" --parallel 3
# 上述免费预览通过后，在已有明确授权内添加 --call-model。
node scripts/project.mjs python scenarios/remotion_edit/verify.py \
  --tasks scenarios/remotion_edit/tasks-v2.json \
  --output-dir "$REMOTION_EXPERIMENT_ROOT/qa-v2"
node scripts/project.mjs python scenarios/remotion_edit/analyze.py \
  --tasks scenarios/remotion_edit/tasks-all.json \
  --split-file scenarios/remotion_edit/split-v2.json \
  --output-dir "$REMOTION_EXPERIMENT_ROOT/analysis-v2"
```

`check_content.py`增加首帧、冻结/循环帧差以及静音窗口的窄检查；它不判定完整剪辑质量，不代替盲评。结果见[第二批记录](../../docs/experiments/remotion-motivation-20261027-v2.md)，不改第一批结果。

后续正在进行[结构化复用四臂实验](structured/README.md)：对照旧工具、结构化工具、学习出的只读接管及普通融合工具，分开衡量工具化和Motif边际效果。[协议与当前证据](../../docs/experiments/remotion-structured-reuse-20261028-v1.md)记录真实跳过、源起点失败和质量边界；没有把局部控制流程成功写成净收益。
