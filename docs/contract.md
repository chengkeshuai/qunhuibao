# 本地 MVP 数据契约 v1

这是已实现的内部契约。已支持本地审稿与分享文件导出；发布结构见qunhuibao/publication.py，接口见qunhuibao/service.py；MCP服务未包含。

messages.json: schema_version=1, conversation(非空字符串), coverage(字符串), messages(非空数组), warnings(字符串数组)。每条消息 id(唯一非空字符串), timestamp(字符串，可空), sender(非空字符串，未知则待确认), text(字符串), attachments(数组，可空)，可选 sources(数组，每项含非空字符串 file 与 locator，用于定位输入文件和行号/JSON路径)。不直接接受HTML。

report.json: schema_version=1, source_digest(messages.json的规范化SHA256), title(非空字符串), summary(非空字符串), conversation(须与messages一致), period(字符串), sections(非空数组)。section含 key(固定枚举 topics/tutorials/assets/notices/questions/highlights/decisions/actions，不重复)、title(字符串)、items(数组)。至少有一个条目。item含 title、body、evidence_refs(消息ID数组)、kind(fact/decision/action/asset/question/suggestion)，可选 owner、due、status。

可选keywords为0–24个字符串，每词去首尾空格后2–40字，NFKC、空格、大小写及已确认别名归一后不得重复。建议Agent选择8–18个具体话题词，数量不足不凑数；必须有消息自身正文依据，昵称、回复引文与附件名不计。显式空数组关闭词云，缺字段时兼容旧报告的有限候选回退。词云以“提及的消息条数”计量，同条出现多次只算一条；搜索结果仍按命中位置计数。它是主题导航，不是完整分词统计或重要性排行。

source_digest 由 json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) 的 UTF-8 字节计算 SHA256，包含消息、来源和导入警告。只变 JSON 缩进不改变摘要；更换或修改材料必须重新提炼报告。prepare 自动写入模板，不能手工编造。摘要能防止误用旧材料，但不代表语义、完整性或来源真伪已验证。

fact/decision/action/asset至少一个有效evidence_ref；question/suggestion允许无引用，但渲染时标记待确认/AI建议。每个ref必须存在。没有证据不等于允许自动推断负责人和日期。报告不得包含额外HTML、URL跳转或脚本属性；未知字段由验证器拒绝。

模块接口：importers.import_source(path:Path, conversation:str|None=None)->dict；validation.validate_messages(data)->dict 和 validate_report(report,messages)->dict 返回原对象或raise ValueError；renderer.render_html(report,messages)->str、render_markdown(report,messages)->str。CLI负责文件写入与输出目录防覆盖；renderer不做I/O写入、不联网。renderer调用validation前必须可独立import，tests使用unittest。

展示：只呈现有内容的主题、决定、行动、资产、待确认栏目并连续编号；原消息正文默认可读，技术字段可折叠，全文转义。封面优先展示真实主题，统计收尾。搜索覆盖报告与原文，结果可点选定位高亮，并逐处切换；支持大小写、全半角和空白容错。actions 中的 suggestion 标为“AI 建议 · 未认领”，负责人/期限默认待确认、状态默认未认领，复制保留标签，并与action分开计数。其他章节的suggestion不进入行动复制清单。不提供无后端支持的“任务已完成同步”承诺。

术语接口：terminology.review_terms(messages)->list[dict]，返回已确认且语境匹配的message_id/original/canonical/rule_id/start/end/reason。start/end为Python原字符串索引，end排除；不能直接当JavaScript UTF-16索引。正式映射只在包内assets/terminology.json维护；prepare输出术语核对.json，包含source_digest/rules_source/matches/scope。核对快照不进入messages或更换摘要，原话引用仍保留原写法；报告采用标准名，搜索可关联本次批准的原写法。无关语境不因词面相近而合并。

2026-11-06第一版扩展：item可选question、answer、conditions、outcome（非空字符串），steps（0–30个非空步骤字符串）。answer或非空steps必须有evidence_refs，即使kind为suggestion或question。程序只验证结构及引用，不能判断步骤是否真实可行。HTML和Markdown均直接显示这些字段，不折叠答案。

render同时生成review.html。editor.render_editor(report,messages)先验证结构，内嵌材料与初始报告SHA256；原件私有。审稿进度包含schema_version=1、fingerprint、source_digest、内部标题摘要、条目及选择/排序、分享标题导语和遮盖设置；恢复时核对初始版本、字段集合、条目ID/归属、类型与原始引用，不能凭导入草稿更换证据。允许修改文本，不自动改变事实类型或更新词库。浏览器本地存储只是便利能力，进度JSON用于可移植保存；不含全部原消息，但仍是私有文件。

分享HTML从选定字段生成固定模板，无原始数据JSON、来源路径、未选条目及消息；选中的原话经显示整理及遮盖后输出。内部标题摘要不自动进入分享。未知敏感信息不能承诺自动识别。分享版搜索范围是当前文件，话题入口只按选中条目出现的词筛选，不声称完整群聊词频。在线发布、访问控制、撤回、跨日搜索仍未实现。
