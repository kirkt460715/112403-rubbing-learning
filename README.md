# 拓印过程学习分析

本地演练资料记录拓印流程观察、材料状态、评分标准版本、匿名参与者实践步骤和作品检查。没有记录的步骤与明确未掌握分别编码。

## 分析能力

`learning_analysis.py` 把每轮观察整理成可复用的分析报告，核心约定：

- **三类结论分开，互不合并**
  - 作品结果：逐条保留 `rubric_version`，评分标准调整后版本不同，不跨版本比较、不排名；
  - 动作掌握：只依据观察员对该步骤的直接观察（`complete`→demonstrated、`partial`→partial_mastery、`assisted`→assisted）；
  - 未观察：明确标记的 `not_observed`（marked_missing）与无观察行（no_record）都保留为 `unknown`，**不默认为未掌握**。
- **学习证据与器材条件分开**：`learning_view` 服务带教人员（薄弱步骤、协助步骤、观察缺口），`equipment_view` 服务物料人员（拓版/纸张批次状态）。建议带 `driver` 字段标明由 `learning` 还是 `equipment` 驱动，模块不输出任何综合质量分。
- **作品不反推动作掌握**：协助完成或缺少直接观察时，作品评分只作侧面参考（`work_only_evidence`），不会把掌握判定升级为 demonstrated。
- **材料状态按时段匹配**：材料记录含 `valid_from`/`valid_to`，按实践日期取生效状态。材料更正后用更正数据重跑即可重算器材侧解释；由观察和作品支持的学习结论不随器材重算改变。
- **引用完整性校验**：跨表引用、步骤名、评分版本与标签不合法时进入报告的 `data_issues`。

## Local checks

Python 3.9 or newer is sufficient. The repository has no third-party runtime dependencies.

Run `python3 input_audit.py` to verify the declared files and columns. Run `python3 -m unittest discover -s tests -v` to check the prepared input contract and the analysis behavior.

Run `python3 learning_analysis.py` for the Chinese text report, or `python3 learning_analysis.py --json` for the structured report. After a material correction, point `--data-dir` at the corrected data directory to recompute the equipment view.

The records are synthetic fixtures. Empty values and status labels retain their literal input meaning. The manifest lists file columns and the stable row identifier used by the input audit.
