"""拓印实践观察分析模块。

把每轮拓印实践的观察记录整理成可复用的分析能力。设计原则：

1. 三类结论严格分开，互不合并：
   - 作品结果（work results）：按评分标准版本（rubric_version）保留，不跨版本比较；
   - 动作掌握（step mastery）：只依据观察员对该步骤的直接观察；
   - 未观察（unknown）：保留"未观察"与"无记录"的字面含义，不默认为未掌握。

2. 学习证据与器材条件分开呈现、分开驱动建议，模块不输出任何综合质量分数。

3. 材料状态按生效时段匹配实践日期；材料更正后用新数据重跑即可重算器材侧解释，
   而由观察与作品支持的学习结论保持不变（重算只重建派生报告，不修改原始记录）。

无第三方运行时依赖，Python 3.9+。
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# 拓印关键动作，按现场流程顺序排列。
STEP_ORDER = ("clean", "place_paper", "press", "ink", "peel")
STEP_LABELS = {
    "clean": "清理拓版",
    "place_paper": "覆纸润纸",
    "press": "压实",
    "ink": "上墨",
    "peel": "揭纸晾干",
}

# 观察结果字面量 -> 掌握判定分组。
# not_observed 与"该实践根本没有该步骤记录"都归入 unknown，
# 但二者在 observation_scope 中分别保留，不被当成未掌握。
RESULT_GROUPS = {
    "complete": "demonstrated",
    "partial": "partial_mastery",
    "assisted": "assisted",
    "not_observed": "unknown",
}

# 作品评分标签 -> 作品层面的解释（仅解释作品，不反推动作掌握）。
SCORE_INTERPRETATIONS = {
    "steady": "作品压力稳定",
    "uneven": "作品压力不均",
    "even": "作品上墨均匀",
    "patchy": "作品上墨不匀",
}

# 器材条件 -> 对作品/表现解释的影响说明（器材侧，不并入学习判断）。
CONDITION_EFFECTS = {
    "good": "材料状态正常，作品表现可直接用于练习讨论",
    "review": "纸张批次处于复核状态，清晰度差异需谨慎归因于个人操作",
    "worn": "拓版磨损，可能造成细节缺失，作品缺陷不能单独归因于参与者动作",
    "unknown": "无匹配时段的材料状态记录，器材影响无法判断",
}


# --------------------------------------------------------------------------- #
# 输入读取
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def load_inputs(data_dir: Path = DATA_DIR) -> Dict[str, List[Dict[str, str]]]:
    """读取全部输入表。空字符串保留字面含义，不做隐式填充。"""
    tables = {}
    for name in (
        "practice",
        "sessions",
        "observations",
        "work_samples",
        "materials",
        "rubrics",
    ):
        tables[name] = _read_csv(Path(data_dir) / f"{name}.csv")
    return tables


def _parse_day(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


# --------------------------------------------------------------------------- #
# 引用完整性校验
# ---------------------------------------------------------------------------

def validate_references(tables: Dict[str, List[Dict[str, str]]]) -> List[str]:
    """检查跨表引用与评分版本/标签的合法性，返回问题描述列表（空列表表示通过）。"""
    issues: List[str] = []

    session_ids = {row["session_id"] for row in tables["sessions"]}
    blocks = {row["block_token"] for row in tables["materials"]}
    practice_ids = {row["practice_id"] for row in tables["practice"]}
    rubric_index = {
        (row["rubric_version"], row["criterion"], row["score_label"]): row
        for row in tables["rubrics"]
    }
    rubric_keys = set(rubric_index)
    rubric_versions = {row["rubric_version"] for row in tables["rubrics"]}

    for row in tables["practice"]:
        if row["session_id"] not in session_ids:
            issues.append(
                f"practice {row['practice_id']}: 未知 session_id {row['session_id']}"
            )
        if row["block_token"] not in blocks:
            issues.append(
                f"practice {row['practice_id']}: 未知 block_token {row['block_token']}"
            )

    for row in tables["observations"]:
        if row["practice_id"] not in practice_ids:
            issues.append(
                f"observation: 未知 practice_id {row['practice_id']}（步骤 {row['step']}）"
            )
        if row["step"] not in STEP_ORDER:
            issues.append(
                f"observation {row['practice_id']}: 未知步骤 {row['step']}"
            )

    practice_dates = {
        row["practice_id"]: _parse_day(
            next(s["practice_date"] for s in tables["sessions"]
                 if s["session_id"] == row["session_id"])
        )
        for row in tables["practice"]
        if row["session_id"] in session_ids
    }

    for row in tables["work_samples"]:
        if row["practice_id"] not in practice_ids:
            issues.append(
                f"work_sample {row['sample_id']}: 未知 practice_id {row['practice_id']}"
            )
        if row["rubric_version"] not in rubric_versions:
            issues.append(
                f"work_sample {row['sample_id']}: 未知评分版本 {row['rubric_version']}"
            )
        key = (row["rubric_version"], row["criterion"], row["score_label"])
        if key not in rubric_keys:
            issues.append(
                f"work_sample {row['sample_id']}: 评分标签 {row['score_label']} "
                f"不属于版本 {row['rubric_version']} 标准 {row['criterion']}"
            )
        elif row["practice_id"] in practice_dates:
            rubric_row = rubric_index[key]
            on_date = practice_dates[row["practice_id"]]
            valid_from = _parse_day(rubric_row["valid_from"])
            valid_to = _parse_day(rubric_row["valid_to"])
            if not (valid_from <= on_date and (valid_to is None or valid_to >= on_date)):
                issues.append(
                    f"work_sample {row['sample_id']}: 评分版本 {row['rubric_version']} "
                    f"在实践日期 {on_date.isoformat()} 不在有效期内"
                )

    return issues


# --------------------------------------------------------------------------- #
# 器材条件（时段匹配）
# ---------------------------------------------------------------------------

def material_at(
    materials: Sequence[Dict[str, str]],
    block_token: str,
    on_date: date,
) -> Dict[str, Optional[str]]:
    """返回某拓版组合在指定日期生效的材料记录。

    同一 block 可能有多条时段记录（如批次/状态更正）。无匹配时 condition 为
    'unknown'，由调用方登记数据问题，绝不臆测状态。
    """
    matches = [
        row
        for row in materials
        if row["block_token"] == block_token
        and _parse_day(row["valid_from"]) <= on_date
        and (_parse_day(row["valid_to"]) is None or _parse_day(row["valid_to"]) >= on_date)
    ]
    if not matches:
        return {
            "block_token": block_token,
            "plate_token": None,
            "paper_lot": None,
            "condition": "unknown",
        }
    row = matches[0]
    return {
        "block_token": row["block_token"],
        "plate_token": row["plate_token"],
        "paper_lot": row["paper_lot"],
        "condition": row["condition"],
    }


# --------------------------------------------------------------------------- #
# 单条实践分析
# ---------------------------------------------------------------------------

def _step_view(
    practice_id: str,
    observations: Sequence[Dict[str, str]],
) -> Dict[str, dict]:
    """按步骤汇总观察范围与掌握判定。

    观察范围区分三种情况：
      observed     —— 有该步骤的观察行；
      marked_missing —— 有观察行但结果明确为 not_observed；
      no_record    —— 该实践没有该步骤的任何观察行。
    后两者的掌握判定都是 unknown，且不会被当成未掌握。
    """
    by_step: Dict[str, Dict[str, str]] = {}
    for row in observations:
        if row["practice_id"] != practice_id:
            continue
        by_step[row["step"]] = row

    view = {}
    for step in STEP_ORDER:
        row = by_step.get(step)
        if row is None:
            scope = "no_record"
            raw_result: Optional[str] = None
            mastery = "unknown"
            observer = None
            observed_at = None
        else:
            raw_result = row["observed_result"]
            observer = row["observer"]
            observed_at = row["observed_at"]
            if raw_result == "not_observed":
                scope = "marked_missing"
                mastery = "unknown"
            else:
                scope = "observed"
                mastery = RESULT_GROUPS.get(raw_result, "other")
        view[step] = {
            "step": step,
            "label": STEP_LABELS[step],
            "observation_scope": scope,
            "observed_result": raw_result,
            "mastery": mastery,
            "observer": observer,
            "observed_at": observed_at,
        }
    return view


def _work_views(
    practice_id: str,
    samples: Sequence[Dict[str, str]],
    rubrics: Sequence[Dict[str, str]],
) -> List[dict]:
    """作品结果视图：逐条保留评分版本，不做跨版本合并或排名。"""
    rubric_index = {
        (row["rubric_version"], row["criterion"], row["score_label"]): row
        for row in rubrics
    }
    views = []
    for row in samples:
        if row["practice_id"] != practice_id:
            continue
        rubric_row = rubric_index.get(
            (row["rubric_version"], row["criterion"], row["score_label"])
        )
        views.append(
            {
                "sample_id": row["sample_id"],
                "rubric_version": row["rubric_version"],
                "criterion": row["criterion"],
                "score_label": row["score_label"],
                "linked_step": rubric_row["step"] if rubric_row else None,
                "interpretation": SCORE_INTERPRETATIONS.get(
                    row["score_label"], row["score_label"]
                ),
            }
        )
    return views


def analyze_practice(
    practice: Dict[str, str],
    tables: Dict[str, List[Dict[str, str]]],
) -> dict:
    """分析单条实践，输出作品结果、动作掌握、观察范围与器材条件（彼此独立）。"""
    practice_id = practice["practice_id"]
    session = next(
        row for row in tables["sessions"] if row["session_id"] == practice["session_id"]
    )
    on_date = _parse_day(session["practice_date"])
    material = material_at(tables["materials"], practice["block_token"], on_date)

    steps = _step_view(practice_id, tables["observations"])
    works = _work_views(practice_id, tables["work_samples"], tables["rubrics"])

    # 协助痕迹：任何步骤由家人/他人协助，或作品在协助下完成，都显式标注，
    # 不把协助下的作品当作独立掌握的证据。
    assisted_steps = [
        step
        for step, item in steps.items()
        if item["mastery"] == "assisted"
    ]

    # 作品可对某个动作提供侧面支持，但只要该步骤没有"独立完成"的直接观察，
    # 掌握判定仍然保留 unknown/assisted，不升级为 demonstrated。
    work_only_steps = []
    for work in works:
        linked = work["linked_step"]
        if linked and linked in steps:
            if steps[linked]["observation_scope"] != "observed":
                work_only_steps.append(
                    {
                        "step": linked,
                        "label": STEP_LABELS.get(linked, linked),
                        "sample_id": work["sample_id"],
                        "note": "作品可侧面参考，但缺少独立完成的直接观察，不据此判定掌握",
                    }
                )

    observed_steps = [
        step for step, item in steps.items()
        if item["observation_scope"] == "observed"
    ]

    return {
        "practice_id": practice_id,
        "session_id": practice["session_id"],
        "practice_date": session["practice_date"],
        "person_token": practice["person_token"],
        "guide_token": practice["guide_token"],
        "block_token": practice["block_token"],
        "observed_steps": observed_steps,
        "step_mastery": steps,
        "work_results": works,
        "work_only_evidence": work_only_steps,
        "assisted_steps": assisted_steps,
        "equipment": {
            "plate_token": material["plate_token"],
            "paper_lot": material["paper_lot"],
            "condition": material["condition"],
            "condition_note": CONDITION_EFFECTS.get(
                material["condition"], material["condition"]
            ),
        },
    }


# --------------------------------------------------------------------------- #
# 汇总视图：学习侧与器材侧分开
# ---------------------------------------------------------------------------

def _learning_view(analyses: Sequence[dict]) -> dict:
    """带教人员视图：步骤薄弱点与观察覆盖缺口，全部由学习证据驱动。"""
    weak_steps: Dict[str, List[str]] = defaultdict(list)
    assisted: Dict[str, List[str]] = defaultdict(list)
    coverage_gaps: Dict[str, List[str]] = defaultdict(list)
    per_practice = []

    for item in analyses:
        gaps = []
        for step in STEP_ORDER:
            mastery = item["step_mastery"][step]["mastery"]
            scope = item["step_mastery"][step]["observation_scope"]
            if mastery in ("partial_mastery", "other"):
                weak_steps[step].append(item["practice_id"])
            if mastery == "assisted":
                assisted[step].append(item["practice_id"])
            if scope in ("marked_missing", "no_record"):
                gaps.append(
                    {
                        "step": step,
                        "label": STEP_LABELS[step],
                        "reason": "明确标记未观察"
                        if scope == "marked_missing"
                        else "无该步骤观察记录",
                    }
                )
                coverage_gaps[step].append(item["practice_id"])
        per_practice.append(
            {
                "practice_id": item["practice_id"],
                "guide_token": item["guide_token"],
                "weak_steps": [
                    s for s in STEP_ORDER
                    if item["step_mastery"][s]["mastery"]
                    in ("partial_mastery", "other")
                ],
                "assisted_steps": item["assisted_steps"],
                "coverage_gaps": gaps,
                "work_only_evidence": item["work_only_evidence"],
            }
        )

    return {
        "by_step": [
            {
                "step": step,
                "label": STEP_LABELS[step],
                "partial_or_weak_practices": sorted(weak_steps.get(step, [])),
                "assisted_practices": sorted(assisted.get(step, [])),
                "not_observed_practices": sorted(coverage_gaps.get(step, [])),
            }
            for step in STEP_ORDER
        ],
        "by_practice": per_practice,
    }


def _equipment_view(analyses: Sequence[dict]) -> dict:
    """物料人员视图：只看器材条件及其影响，与学习判断隔离。"""
    by_condition: Dict[str, List[dict]] = defaultdict(list)
    for item in analyses:
        equipment = item["equipment"]
        by_condition[equipment["condition"]].append(
            {
                "practice_id": item["practice_id"],
                "block_token": item["block_token"],
                "plate_token": equipment["plate_token"],
                "paper_lot": equipment["paper_lot"],
            }
        )
    return {
        "conditions": [
            {
                "condition": condition,
                "condition_note": CONDITION_EFFECTS.get(condition, condition),
                "affected_practices": rows,
            }
            for condition, rows in sorted(by_condition.items())
        ],
    }


def _work_results_view(analyses: Sequence[dict]) -> dict:
    """作品结果按评分版本分组。评分标准调整后版本不同，分数不跨版本比较。"""
    versions: Dict[str, dict] = defaultdict(
        lambda: {"criteria": defaultdict(list)}
    )
    for item in analyses:
        for work in item["work_results"]:
            versions[work["rubric_version"]]["criteria"][work["criterion"]].append(
                {
                    "practice_id": item["practice_id"],
                    "sample_id": work["sample_id"],
                    "score_label": work["score_label"],
                    "interpretation": work["interpretation"],
                }
            )
    grouped = []
    for version in sorted(versions):
        criteria = [
            {"criterion": criterion, "samples": samples}
            for criterion, samples in sorted(versions[version]["criteria"].items())
        ]
        grouped.append({"rubric_version": version, "criteria": criteria})
    return {"by_rubric_version": grouped}


def _recommendations(analyses: Sequence[dict]) -> List[dict]:
    """建议必须标明驱动来源：learning（学习证据）或 equipment（器材条件）。

    缺项只产生"补观察"建议，不产生"补练习/判定未掌握"建议；
    器材问题只产生物料处置建议，不与学习建议合并。
    """
    recs: List[dict] = []

    # 学习证据驱动
    weak: Dict[str, List[str]] = defaultdict(list)
    assisted: Dict[str, List[str]] = defaultdict(list)
    gaps: Dict[str, List[str]] = defaultdict(list)
    work_only: Dict[str, List[str]] = defaultdict(list)

    for item in analyses:
        for step in STEP_ORDER:
            mastery = item["step_mastery"][step]["mastery"]
            scope = item["step_mastery"][step]["observation_scope"]
            if mastery in ("partial_mastery", "other"):
                weak[step].append(item["practice_id"])
            if mastery == "assisted":
                assisted[step].append(item["practice_id"])
            if scope in ("marked_missing", "no_record"):
                gaps[step].append(item["practice_id"])
        for entry in item["work_only_evidence"]:
            work_only[entry["step"]].append(item["practice_id"])

    for step in STEP_ORDER:
        if weak[step]:
            recs.append(
                {
                    "driver": "learning",
                    "type": "reinforce_step",
                    "step": step,
                    "label": STEP_LABELS[step],
                    "practices": sorted(weak[step]),
                    "action": "下一轮增加该步骤示范并安排专项练习",
                }
            )
        if assisted[step]:
            recs.append(
                {
                    "driver": "learning",
                    "type": "independent_practice",
                    "step": step,
                    "label": STEP_LABELS[step],
                    "practices": sorted(assisted[step]),
                    "action": "安排无协助重复练习，确认能否独立完成",
                }
            )
        if gaps[step]:
            recs.append(
                {
                    "driver": "learning",
                    "type": "observe_missing_step",
                    "step": step,
                    "label": STEP_LABELS[step],
                    "practices": sorted(gaps[step]),
                    "action": "下一轮补齐该步骤观察；当前不得判定为未掌握",
                }
            )
        if work_only[step]:
            recs.append(
                {
                    "driver": "learning",
                    "type": "verify_with_direct_observation",
                    "step": step,
                    "label": STEP_LABELS[step],
                    "practices": sorted(work_only[step]),
                    "action": "作品仅提供侧面参考，需直接观察确认动作掌握",
                }
            )

    # 器材条件驱动（与学习证据完全分开）
    equipment_groups: Dict[str, List[dict]] = defaultdict(list)
    for item in analyses:
        equipment_groups[item["equipment"]["condition"]].append(item)
    for condition, items in sorted(equipment_groups.items()):
        if condition == "good":
            continue
        practices = sorted(item["practice_id"] for item in items)
        if condition == "worn":
            action = "安排更换磨损拓版；更换前相关作品缺陷不单独归因于参与者"
        elif condition == "review":
            action = "复核纸张批次并视情况换纸；复核期间清晰度差异谨慎归因"
        elif condition == "unknown":
            action = "补登材料状态时段记录，再重算器材侧解释"
        else:
            action = "核实材料状态并安排处置"
        recs.append(
            {
                "driver": "equipment",
                "type": "material_action",
                "condition": condition,
                "practices": practices,
                "action": action,
            }
        )

    return recs


# --------------------------------------------------------------------------- #
# 总入口
# ---------------------------------------------------------------------------

def build_analysis(
    tables: Optional[Dict[str, List[Dict[str, str]]]] = None,
    data_dir: Path = DATA_DIR,
) -> dict:
    """从输入表构建完整分析报告。

    材料状态更正时，用更正后的 materials 表（或更正后的 data 目录）重新调用本函数
    即可重算器材侧解释；学习侧结论来自观察记录与作品记录，重算保持不变。
    """
    if tables is None:
        tables = load_inputs(data_dir)

    issues = validate_references(tables)
    analyses = [analyze_practice(row, tables) for row in tables["practice"]]

    return {
        "schema_version": 1,
        "steps": [
            {"step": step, "label": STEP_LABELS[step]} for step in STEP_ORDER
        ],
        "data_issues": issues,
        "practices": analyses,
        "learning_view": _learning_view(analyses),
        "equipment_view": _equipment_view(analyses),
        "work_results_view": _work_results_view(analyses),
        "recommendations": _recommendations(analyses),
    }


def render_text_report(report: dict) -> str:
    """生成供带教/物料人员现场阅读的中文文本报告。"""
    lines: List[str] = []
    lines.append("拓印实践分析报告")
    lines.append("=" * 24)

    if report["data_issues"]:
        lines.append("\n[数据问题]")
        lines.extend(f"- {issue}" for issue in report["data_issues"])

    lines.append("\n一、各实践：作品结果 / 动作掌握 / 观察范围（三者分开）")
    for item in report["practices"]:
        lines.append(
            f"\n实践 {item['practice_id']}（场次 {item['session_id']}，"
            f"参与者 {item['person_token']}，讲解 {item['guide_token']}）"
        )
        equipment = item["equipment"]
        lines.append(
            f"  器材：拓版 {equipment['plate_token']} / 纸张 {equipment['paper_lot']}"
            f" / 状态 {equipment['condition']}（{equipment['condition_note']}）"
        )
        if item["assisted_steps"]:
            lines.append(f"  协助步骤：{', '.join(item['assisted_steps'])}")
        lines.append("  步骤掌握：")
        for step in STEP_ORDER:
            view = item["step_mastery"][step]
            scope_text = {
                "observed": "已观察",
                "marked_missing": "明确未观察",
                "no_record": "无记录",
            }[view["observation_scope"]]
            raw = view["observed_result"] or "—"
            lines.append(
                f"    - {view['label']}（{step}）：判定={view['mastery']}，"
                f"观察范围={scope_text}，原始记录={raw}"
            )
        if item["work_results"]:
            lines.append("  作品结果（保留评分版本，不与其他版本比较）：")
            for work in item["work_results"]:
                lines.append(
                    f"    - {work['sample_id']}：版本 {work['rubric_version']} / "
                    f"{work['criterion']}={work['score_label']}（{work['interpretation']}）"
                )
        else:
            lines.append("  作品结果：无")
        for entry in item["work_only_evidence"]:
            lines.append(
                f"  注意：{entry['label']}仅有作品侧面参考（{entry['sample_id']}），{entry['note']}"
            )

    lines.append("\n二、学习视图（带教人员，按步骤汇总，学习证据驱动）")
    for row in report["learning_view"]["by_step"]:
        lines.append(
            f"- {row['label']}（{row['step']}）：薄弱 {row['partial_or_weak_practices'] or '无'}；"
            f"协助 {row['assisted_practices'] or '无'}；"
            f"未观察 {row['not_observed_practices'] or '无'}（缺项不按未掌握处理）"
        )

    lines.append("\n三、器材视图（物料人员，器材条件驱动，与学习判断隔离）")
    for row in report["equipment_view"]["conditions"]:
        practices = ", ".join(p["practice_id"] for p in row["affected_practices"])
        lines.append(
            f"- 状态 {row['condition']}：{row['condition_note']}；影响实践 {practices}"
        )

    lines.append("\n四、作品结果（按评分版本分组，不跨版本比较或排名）")
    for version_block in report["work_results_view"]["by_rubric_version"]:
        lines.append(f"- 评分版本 {version_block['rubric_version']}：")
        for criterion in version_block["criteria"]:
            labels = ", ".join(
                f"{sample['practice_id']}={sample['score_label']}"
                for sample in criterion["samples"]
            )
            lines.append(f"    {criterion['criterion']}：{labels}")

    lines.append("\n五、建议（标注驱动来源；不输出综合质量分）")
    for rec in report["recommendations"]:
        driver = "学习证据" if rec["driver"] == "learning" else "器材条件"
        target = rec.get("label") or rec.get("condition")
        lines.append(
            f"- [{driver}] {rec['type']} {target}：{rec['action']} "
            f"（涉及 {', '.join(rec['practices'])}）"
        )

    return "\n".join(lines)


def main(argv: Optional[Iterable[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="拓印实践学习分析")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非中文文本报告")
    parser.add_argument(
        "--data-dir",
        default=str(DATA_DIR),
        help="输入数据目录（材料更正后可指向更正后的目录重算）",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = build_analysis(data_dir=Path(args.data_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
