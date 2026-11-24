# 拓印过程学习分析

本地演练资料记录拓印流程观察、材料状态、评分标准版本、匿名参与者实践步骤和作品检查。没有记录的步骤与明确未掌握分别编码。

## Local checks

Python 3.9 or newer is sufficient. The repository has no third-party runtime dependencies.

Run `python3 input_audit.py` to verify the declared files and columns. Run `python3 -m unittest discover -s tests -v` to check the prepared input contract.

The records are synthetic fixtures. Empty values and status labels retain their literal input meaning. The manifest lists file columns and the stable row identifier used by the input audit.
