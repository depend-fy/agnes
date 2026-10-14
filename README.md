# 智鉴 AI（VeriMind AI）

面向 AI 生成文本的**多角色幻觉检测、证据溯源、问题归因与基于证据的自动修正** Demo。

- 输入一段 AI 生成文本
- 拆成原子事实主张
- 多角色协同检测（事实审查员 / 证据审查员 / 独立复核员，可真实多模型）
- 检索可信外部来源（Crossref + OpenAlex，免费公开 API）
- 匹配证据与主张，判定六态 / 识别八类问题
- 基于证据生成修正建议（不编造证据）
- 独立复核修正结果（是否解决原问题 / 是否引入新错误）
- 输出可追溯的检测报告

## 核心原则

- **无证据 ≠ 错误**：查不到可信证据时标记"暂无法核验 / 证据不足"，绝不武断判错。
- **不伪造证据**：修正在无证据时不强行生成，标注"需人工"。
- **不展示未校准概率**：只展示有明确含义的状态与定性风险。
- **区分真实调用与模拟**：单模型多角色或无 key 时明确标注"桩/模拟"。
- **可追溯**：每条证据带来源名 / URL / 检索时间；角色判断带 model_tag。

## 技术栈

| 维度   | 选择                                        |
| ---- | ----------------------------------------- |
| 语言   | Python 3.10+（当前 3.13 64-bit）              |
| Web  | Streamlit                                 |
| 数据结构 | Pydantic v2                               |
| HTTP | httpx                                     |
| 检索   | Crossref + OpenAlex（无 key）                |
| LLM  | Agnes（事实审查员）+ DeepSeek（证据/复核），OpenAI 兼容端点 |
| 测试   | pytest                                    |

## 目录结构

```
verimind/
├── app/                 # Streamlit 入口与页面
│   └── main.py
├── core/                # 数据结构 / 枚举 / 配置
│   ├── enums.py
│   ├── models.py
│   └── config.py
├── claims/              # 原子事实主张提取（规则桩 → 阶段 3 可换 LLM）
├── models/              # LLM 适配层（OpenAI 兼容 + 离线桩 + 工厂）
├── roles/               # 三角色（事实/证据/复核）提示词与调用
├── retrieval/           # 双入口检索（学术：Crossref+OpenAlex；其他：Wikipedia+网页）+ 快照兜底
│   ├── crossref.py
│   ├── openalex.py
│   ├── web_search.py    # 非学术入口（Wikipedia REST API + DuckDuckGo HTML）
│   ├── searcher.py      # 路由：DOI 走学术、非学术走双入口合并
│   └── snapshot.py
├── attribution/         # 六态 / 八类问题分类（含 source_tier 保守化）
├── correction/          # 基于证据的修正
├── review/              # 独立复核
├── report/              # 报告组装
├── pipeline.py          # 端到端管线
├── metrics.py           # 成本 / 延迟 / token 统计
├── evaluation/          # 标注测试集评测（混淆矩阵 / F1 / 可追溯率）
├── examples/            # 示例文本 + 预取证据快照
│   └── evidence_snapshot.json
├── ui/                  # 视图逻辑层（可信度评分环 / 共识 / 证据链 / 重写建议 / 报告导出）
├── tests/               # 自动化测试（101 项）
└── docs/                # 答辩材料
```

## 安装与运行

### 1. 环境

```powershell
cd D:\agnes-harness\verimind
# 用 64 位 Python 3.13 建虚拟环境（示例，按你机器的 Python 路径调整）
& "D:\python3.13\python.exe" -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. 配置

```powershell
Copy-Item .env.example .env
```

用记事本打开 `.env`，填两个 API key（**key 只进 .env，勿提交 Git / 勿贴聊天**）：

```
VERIMIND_MODE=live
VERIMIND_AGNESES_API_KEY=你的Agnes密钥
VERIMIND_DEEPSEEK_API_KEY=你的DeepSeek密钥
```

> 不填 key 也可以跑：`VERIMIND_MODE=stub` 时用离线桩（不联网、不调模型），闭环仍可演示。

### 3. 运行

```powershell
.venv\Scripts\python.exe -m streamlit run app/main.py
```

浏览器打开 `http://localhost:8501`。

### 4. 测试

```powershell
.venv\Scripts\python.exe -m pytest -q
```

预期 `101 passed`。

> 说明：全量测试含真实网络检索（Crossref/OpenAlex），需联网；约 17~30 秒。  
> 离线快速验证（跳过网络检索与 LLM 管线测试）：
>
> ```powershell
> .venv\Scripts\python.exe -m pytest tests/test_snapshot.py tests/test_edge_cases.py tests/test_correction_review.py tests/test_models.py tests/test_roles.py tests/test_claims.py tests/test_attribution.py tests/test_core.py tests/test_ui.py tests/test_fixes.py tests/test_two_entry.py tests/test_metrics_evaluation.py -q
> ```

## 核验状态（六态）

| 状态    | 含义            |
| ----- | ------------- |
| 已核实   | 现有证据能支持该主张    |
| 存在矛盾  | 可信证据与该主张冲突    |
| 部分支持  | 证据只支持主张的一部分   |
| 证据不足  | 已有材料不足以支持或反驳  |
| 暂无法核验 | 当前检索条件下无法可靠判断 |
| 来源冲突  | 不同可信来源信息不一致   |

## 问题类型（八类）

事实错误 / 引用不存在或元数据不匹配 / 引用与结论不匹配 / 数字错误 / 时间人物机构错误 / 逻辑推断过度 / 缺少必要证据 / 来源冲突。

> 注意：这些是系统**基于可观察证据**作出的判断，不代表系统能知道另一个模型"内部为什么出错"。

## 双入口证据检索（学术 + 其他）

| 入口 | 检索源 | 适用主张 |
|---|---|---|
| 学术 | Crossref + OpenAlex（免密钥） | 含 DOI 的引用主张（METADATA） |
| 其他 | Wikipedia + 通用网页（免密钥） | 非学术主张（EXISTENCE / TIME_PERSON_ORG / GENERAL / CAUSAL / NUMERIC / LOGIC） |

- **证据等级保守化**：`Evidence.source_tier` 分 `academic` / `wikipedia` / `web` 三级；普通网页证据**不能**把主张升到“已核实”，顶多“部分支持（低质来源，仅供参考）”。
- **失败静默降级**：任一源超时/限流 → 该源返回空，不崩不卡，与学术检索行为一致。
- **配置开关**：`VERIMIND_ENABLE_WEB_SEARCH=false` 可一键关闭非学术入口，仅保留学术检索。

## 演示案例

`examples/sample_texts.py` 含预置案例（虚构 DOI / 数字错误 / 来源冲突 / 正确事实）。  
现场演示建议用**带真实 DOI** 的文本（如 `10.1038/nature12373`），可完整展示  
"检索 → 证据 → 修正 → 复核"链路。

## 证据快照（离线兜底）

`examples/evidence_snapshot.json` 是**联网时实际检索**预取的真实证据，现场断网/限流时自动兜底，  
保证 Demo 不卡死。报告页会标注证据来源是"实时检索"还是"本地预取快照"（不谎称刚检索）。

重新预取快照（联网时）：

```powershell
.venv\Scripts\python.exe -c "from retrieval.searcher import retrieve; from retrieval.snapshot import save_snapshot; from claims.extractor import extract; ev=retrieve(extract('某研究发表于 2013 年，DOI 为 10.1038/nature12373，证明精度提高 40%。')); save_snapshot(ev); print('saved', len(ev))"
```

## 指标口径（阶段 6 初步）

系统有效性需在**人工标注测试集**上评测（见下），指标必须来自真实运行，禁止未测宣称。  
当前为 **Demo / 初步结果**：

- 幻觉检测精确率 / 召回率、误报率
- 引用真实性识别、证据支持关系判断
- 修正成功率、修正后剩余错误率、新增错误率
- 证据可追溯率、平均响应时间、单次成本

> 被测模型不能给自己输出打客观分；需独立可信证据标注。数据不足时标注"初步结果"。  
> 测试集规模与条件需记录（阶段 7 补完整评测页与基线对比）。

## 已知局限

- 检索只到**摘要/元数据层**，未获取全文；摘要不足以判断结论时落"证据不足/暂无法核验"。
- 修正为**单次生成**，未做无限循环重生成；复核失败只提示风险。
- 角色判断目前按**整体一条**输出（未逐 claim 拆分），后续可细化。
- 指标为初步结果，评测集规模小，未做大规模基线对比（阶段 7 完善）。

## 后续规划（阶段 7）

- 可重复演示案例 + 演示脚本 + 答辩材料。
- 完整评测页（测试集表现、错误类型分布、基线对比）。
- 成本/延迟统计真实入账。
- 升级为完整 Web 产品（FastAPI 后端 + 前端）的架构预留。
