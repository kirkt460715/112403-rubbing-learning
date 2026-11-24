"""learning_analysis 的行为测试。

覆盖需求中的关键约定：
- 缺项（not_observed / 无记录）保留为 unknown，不默认未掌握；
- 作品结果、动作掌握、未观察三类结论分开，且作品保留评分版本；
- 学习证据与器材条件分开驱动建议，不存在综合质量分；
- 材料状态按时段匹配，更正后可重算器材解释，学习结论保持不变；
- 协助下完成的动作不判为独立掌握；
- 评分标准调整后不同版本不合并比较。
"""

import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from learning_analysis import (
    STEP_ORDER,
    build_analysis,
    load_inputs,
    main,
    material_at,
    render_text_report,
    validate_references,
)


def analysis():
    return build_analysis(load_inputs(ROOT / "data"))


def by_id(report):
    return {item["practice_id"]: item for item in report["practices"]}


class ObservationScopeTests(unittest.TestCase):
    def test_missing_and_not_observed_remain_unknown_not_failed(self):
        report = analysis()
        items = by_id(report)

        # P02 clean 明确标记 not_observed -> unknown，而不是未掌握
        self.assertEqual(
            items["P02"]["step_mastery"]["clean"]["observation_scope"],
            "marked_missing",
        )
        self.assertEqual(items["P02"]["step_mastery"]["clean"]["mastery"], "unknown")

        # P05 没有任何观察行 -> 全部 no_record，掌握判定全部 unknown
        p05 = items["P05"]
        for step in STEP_ORDER:
            self.assertEqual(
                p05["step_mastery"][step]["observation_scope"], "no_record"
            )
            self.assertEqual(p05["step_mastery"][step]["mastery"], "unknown")

        # 任何报告字段中都不应出现把缺项当成未掌握的判定
        all_mastery = {
            item["step_mastery"][step]["mastery"]
            for item in report["practices"]
            for step in STEP_ORDER
        }
        self.assertNotIn("not_mastered", all_mastery)

    def test_observed_results_map_to_mastery_groups(self):
        items = by_id(analysis())
        p01 = items["P01"]
        self.assertEqual(p01["step_mastery"]["clean"]["mastery"], "demonstrated")
        self.assertEqual(p01["step_mastery"]["place_paper"]["mastery"], "demonstrated")
        self.assertEqual(p01["step_mastery"]["ink"]["mastery"], "partial_mastery")

        # 协助完成：单独分组，不算独立掌握
        self.assertEqual(items["P03"]["step_mastery"]["press"]["mastery"], "assisted")
        self.assertEqual(items["P03"]["assisted_steps"], ["press"])


class WorkResultSeparationTests(unittest.TestCase):
    def test_work_results_keep_rubric_version_and_do_not_overwrite_mastery(self):
        report = analysis()
        items = by_id(report)

        # P03 压实由家人协助；即使作品 pressure=steady，掌握判定仍是 assisted
        p03 = items["P03"]
        work = next(w for w in p03["work_results"] if w["sample_id"] == "W03")
        self.assertEqual(work["rubric_version"], "R1")
        self.assertEqual(work["score_label"], "steady")
        self.assertEqual(work["linked_step"], "press")
        # P03 压实有直接观察（assisted），因此作品不属于"仅作品证据"，
        # 但 steady 作品同样不能把 assisted 升级为 demonstrated
        self.assertEqual(p03["step_mastery"]["press"]["mastery"], "assisted")
        self.assertFalse(
            any(e["step"] == "press" for e in p03["work_only_evidence"])
        )

        # P05 无任何步骤观察，但有 ink 作品 -> 登记为仅作品侧面证据，掌握仍 unknown
        p05 = items["P05"]
        self.assertTrue(any(e["step"] == "ink" for e in p05["work_only_evidence"]))
        self.assertEqual(p05["step_mastery"]["ink"]["mastery"], "unknown")

    def test_rubric_versions_are_separated_not_merged_or_ranked(self):
        report = analysis()
        versions = {
            block["rubric_version"]: block
            for block in report["work_results_view"]["by_rubric_version"]
        }
        self.assertEqual(set(versions), {"R1", "R2"})
        r2_labels = [
            sample["score_label"]
            for criterion in versions["R2"]["criteria"]
            for sample in criterion["samples"]
        ]
        self.assertIn("even", r2_labels)
        self.assertIn("patchy", r2_labels)

        # 报告里没有任何综合质量分/排名字段
        serialized = json.dumps(report, ensure_ascii=False)
        for forbidden in ("quality_score", "composite_score", "ranking", "rank"):
            self.assertNotIn(forbidden, serialized)


class EquipmentTimelineTests(unittest.TestCase):
    def test_material_condition_matched_by_validity_window(self):
        tables = load_inputs(ROOT / "data")

        # B1 在 10-03 是 good，10-06 起变为 review
        good = material_at(tables["materials"], "B1", date(2026, 10, 3))
        review = material_at(tables["materials"], "B1", date(2026, 10, 6))
        self.assertEqual(good["condition"], "good")
        self.assertEqual(review["condition"], "review")
        self.assertEqual(review["paper_lot"], "P02")

        # B2 全程 worn
        self.assertEqual(
            material_at(tables["materials"], "B2", date(2026, 10, 3))["condition"],
            "worn",
        )

        # 无匹配时段 -> unknown，不臆测
        missing = material_at(tables["materials"], "B9", date(2026, 10, 3))
        self.assertEqual(missing["condition"], "unknown")

    def test_equipment_and_learning_views_are_separate(self):
        report = analysis()
        # 器材视图只含条件信息，不含掌握判定
        equipment_text = json.dumps(report["equipment_view"], ensure_ascii=False)
        self.assertNotIn("mastery", equipment_text)
        # 学习视图不含器材条件
        learning_text = json.dumps(report["learning_view"], ensure_ascii=False)
        self.assertNotIn("condition", learning_text)

        conditions = {
            block["condition"]
            for block in report["equipment_view"]["conditions"]
        }
        self.assertEqual(conditions, {"good", "worn"})

    def test_material_correction_recomputes_equipment_but_keeps_learning(self):
        tables = load_inputs(ROOT / "data")
        before = build_analysis(tables)

        # 模拟材料状态更正：B1 的 P01 纸张批次在 S1 当天即应标记为 review
        corrected = copy.deepcopy(tables)
        for row in corrected["materials"]:
            if row["block_token"] == "B1" and row["paper_lot"] == "P01":
                row["condition"] = "review"
        after = build_analysis(corrected)

        before_items = by_id(before)
        after_items = by_id(after)

        # 器材侧重算：P01/P02 的条件从 good 变为 review
        self.assertEqual(before_items["P01"]["equipment"]["condition"], "good")
        self.assertEqual(after_items["P01"]["equipment"]["condition"], "review")
        self.assertEqual(after_items["P02"]["equipment"]["condition"], "review")

        # 学习侧结论原样保留：观察与作品支持的判断不随材料更正改变
        for pid in ("P01", "P02", "P03", "P04", "P05"):
            self.assertEqual(
                before_items[pid]["step_mastery"],
                after_items[pid]["step_mastery"],
            )
            self.assertEqual(
                before_items[pid]["work_results"],
                after_items[pid]["work_results"],
            )

        # 更正后建议中器材驱动与学习驱动仍然分开
        drivers = {rec["driver"] for rec in after["recommendations"]}
        self.assertEqual(drivers, {"learning", "equipment"})
        equipment_recs = [
            rec for rec in after["recommendations"] if rec["driver"] == "equipment"
        ]
        self.assertTrue(any(rec["condition"] == "review" for rec in equipment_recs))


class RecommendationTests(unittest.TestCase):
    def test_weak_step_demo_recommendation_is_learning_driven(self):
        report = analysis()
        recs = report["recommendations"]
        ink_rec = next(
            rec
            for rec in recs
            if rec["driver"] == "learning"
            and rec["type"] == "reinforce_step"
            and rec["step"] == "ink"
        )
        # P01 上墨 partial -> 增加示范/练习
        self.assertEqual(ink_rec["practices"], ["P01"])

    def test_missing_steps_yield_observe_only_not_remediation(self):
        report = analysis()
        observe_recs = [
            rec
            for rec in report["recommendations"]
            if rec["type"] == "observe_missing_step"
        ]
        # 每个关键步骤都有至少一轮未观察，建议只能是"补观察"
        self.assertTrue(observe_recs)
        for rec in observe_recs:
            self.assertEqual(rec["driver"], "learning")
            self.assertIn("不得判定为未掌握", rec["action"])

        # 缺项绝不产生"增加练习"类补救建议
        remedial = [
            rec
            for rec in observe_recs
            if rec["type"] in ("reinforce_step", "independent_practice")
        ]
        self.assertEqual(remedial, [])

    def test_assisted_step_gets_independent_practice_recommendation(self):
        report = analysis()
        rec = next(
            rec
            for rec in report["recommendations"]
            if rec["type"] == "independent_practice"
            and rec["step"] == "press"
        )
        self.assertEqual(rec["practices"], ["P03"])

    def test_worn_plate_generates_equipment_only_recommendation(self):
        report = analysis()
        worn_rec = next(
            rec
            for rec in report["recommendations"]
            if rec["driver"] == "equipment" and rec["condition"] == "worn"
        )
        self.assertEqual(worn_rec["practices"], ["P03"])
        self.assertIn("更换", worn_rec["action"])

        # 同一条建议不能同时混入学学习字段
        self.assertNotIn("step", worn_rec)

    def test_no_recommendation_merges_learning_and_equipment(self):
        report = analysis()
        for rec in report["recommendations"]:
            self.assertIn(rec["driver"], ("learning", "equipment"))
            if rec["driver"] == "learning":
                self.assertNotIn("condition", rec)
            else:
                self.assertNotIn("step", rec)


class ReferenceValidationTests(unittest.TestCase):
    def test_clean_fixtures_pass_validation(self):
        self.assertEqual(validate_references(load_inputs(ROOT / "data")), [])

    def test_unknown_rubric_label_is_flagged(self):
        tables = load_inputs(ROOT / "data")
        tables["work_samples"][0]["score_label"] = "blurry"
        issues = validate_references(tables)
        self.assertTrue(any("W01" in issue for issue in issues))

    def test_unknown_practice_reference_is_flagged(self):
        tables = load_inputs(ROOT / "data")
        tables["observations"].append(
            {
                "practice_id": "P99",
                "step": "ink",
                "observed_result": "complete",
                "observer": "O1",
                "observed_at": "2026-10-03T10:00:00",
            }
        )
        issues = validate_references(tables)
        self.assertTrue(any("P99" in issue for issue in issues))

    def test_expired_rubric_version_is_flagged(self):
        tables = load_inputs(ROOT / "data")
        # P04 发生在 2026-10-17，而 R1 有效期截止 2026-10-10
        tables["work_samples"][3]["rubric_version"] = "R1"
        tables["work_samples"][3]["criterion"] = "pressure"
        tables["work_samples"][3]["score_label"] = "steady"
        issues = validate_references(tables)
        self.assertTrue(
            any("W04" in issue and "有效期" in issue for issue in issues)
        )


class CliTests(unittest.TestCase):
    def test_text_report_contains_three_separated_conclusions(self):
        report = analysis()
        text = render_text_report(report)
        self.assertIn("作品结果", text)
        self.assertIn("动作掌握", text)
        self.assertIn("学习视图", text)
        self.assertIn("器材视图", text)
        self.assertIn("不输出综合质量分", text)
        # 缺项语义在文本中可见
        self.assertIn("明确未观察", text)
        self.assertIn("无记录", text)

    def test_cli_json_output_roundtrips(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--json", "--data-dir", str(ROOT / "data")])
        decoded = json.loads(buf.getvalue())
        self.assertEqual(len(decoded["practices"]), 5)
        self.assertTrue(decoded["learning_view"])
        self.assertTrue(decoded["equipment_view"])

    def test_alt_data_dir_rerun_after_correction(self):
        tables = load_inputs(ROOT / "data")
        corrected = copy.deepcopy(tables)
        for row in corrected["materials"]:
            if row["block_token"] == "B2":
                row["condition"] = "good"

        import csv as _csv

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, rows in corrected.items():
                with (tmp_path / f"{name}.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as stream:
                    writer = _csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)
            rerun = build_analysis(data_dir=tmp_path)

        items = by_id(rerun)
        self.assertEqual(items["P03"]["equipment"]["condition"], "good")
        # 学习判断仍然基于原始观察，不随器材重算而变
        self.assertEqual(items["P03"]["step_mastery"]["press"]["mastery"], "assisted")


if __name__ == "__main__":
    unittest.main()
