# Remotion错误反馈与单题局部恢复

- 实验ID：`remotion-structured-reuse-20261028-recovery-v3`。状态：修复、真实MCP检查、完整回归和1条真实局部恢复均已完成；不主张Motif降本。
- 触发：[v2](remotion-structured-reuse-20261028-v2.md)的typed/t34使用`src="bunny_a_24.mp4"`而未用`staticFile()`，实际渲染连续三次404。[Remotion官方说明](https://www.remotion.dev/docs/staticfile)要求通过该API获得public素材URL。MCP却只向模型返回通用`Error executing tool render_composition`；模型没有拿到可操作的失败原因，最终如实报告未交付。

本修复把已知守卫／媒体失败从普通ValueError改为MCP公开ToolError，保留有界错误正文及isError，不改变读写权限、源码版本检查或渲染成功判据。原v1/v2独立代码快照保持冻结。原认证库锁定旧server源码，**应拒绝新代码**，不能修改旧manifest摘要绕过；本轮只用typed baseline，不运行旧库execute。后续若发布新库，必须重新完成认证。

调用前用真实stdio MCP验证旧源码拒绝原因可见、未使用staticFile的实际404可见、失败不发布video，再恢复正确源码检查真实视频和JPEG。全仓回归另记，不用确定性检查冒充模型恢复。

只做1条同题局部恢复：`tasks-recovery-v3.json`保留t34题面和冻结QA，新增明确恢复范围；从v2失败源码原样开始，记录初始源码SHA。让真实模型先获取当前错误再局部修复、渲染并检查。它不是新独立任务，也不能把其请求数与从零完整任务直接作收益对照。失败原结果不删除、不覆盖。

运行于新的`code-structured-v3`，结果`structured-v1/runs/recovery-v3/typed/t34_two_views/`。沿用deepseek-flash、reasoning off、6000输出上限、累计不限费用授权；v2结束且无账本writer、免费预览与上述真实MCP检查通过后，才串行开始。成本包含先前失败与本次恢复，账单仍未知。

实际15项无模型MCP检查全部通过：包括明确陈旧源码原因、真实404正文可见、失败不发布视频、正常恢复渲染／全解码与真实JPEG，以及累计模型账本未变化。检查耗时58.239秒、0模型请求。原认证库对新server源码如期拒绝；没有修改旧manifest或跳过守卫。

完整回归使用既有精确白名单OCR-v1与私有Poppler环境，Python1750通过／4跳过，Node1387通过／4跳过／0失败；没有付费模型key。这只说明工程回归，实际恢复另列。

真实模型恢复共**13请求、129.648秒、USD0.00876384代理估费**，另17次Files POST200传输；verified skip为0。它先实际触发一次同样404，收到包含具体原因的错误，再只增加staticFile导入和修改两处素材URL表达式。框架的错误前缀仍在，错误正文不再仅有通用报错。

- 初始源码SHA：`75eb2d2bd6b805aabc60da2e9ecf5998a25746bcb831fb8bfc4f6c44ee0d6a0e`，与失败run逐字相同，已写有效配置。
- 修复后SHA：`f2058fe46729a85094e47ee42c151473e9353a5f6c7a2013db2a6e72f4edeb6d`。
- 视频640×360／30fps／180帧，全解码通过；四个源像素采样MAE约3.56、3.35、2.94、2.77，均在原阈值16内；发布视频与当前entry源码摘要匹配。Agent抽帧未发现新增重大错误，仍不是人工盲评。

原14请求／USD0.00522619失败与本13请求恢复均保留，总计27请求／USD0.01399003；不能把局部修复13与从零完整任务14直接相减当节省。本轮仅支持有信息的错误反馈帮助这一故障恢复，不证明一般恢复效率或因果优越性，也没有新Motif认证。

全部阶段结束时，共41种不同技术题配置、71条物理会话（包含对照、同题复测、旧probe／中断恢复及本局部恢复），累计2164推理请求、276次Files POST200。全部推理HTTP200且usage完整；工具错误与任务失败仍独立记录。观察估费USD1.63269145，checkpoint保守值USD1.63269168保留；账单、CPU、网络、维护与人工成本未核对／未货币化。原累计账本各冻结前缀均核验不变，付费runner和本实验容器已清空，正式服务未修改。
