from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

import extract_structured_pdf as extractor  # noqa: E402


def word(text: str, x0: float, x1: float, top: float) -> dict[str, float | str]:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 10}


def sequence_profile() -> dict[str, object]:
    profile = extractor.load_profile(None)
    profile = extractor.deep_merge(
        profile,
        {
            "layout": {
                "columns": "2",
                "column_split_ratio": 0.5,
                "top_margin_ratio": 0.05,
                "bottom_margin_ratio": 0.04,
            },
            "entry": {
                "mode": "sequence",
                "title_sequence": [
                    {
                        "field": "display_name",
                        "pattern": r"(?P<value>项目[甲乙丙丁])",
                    },
                    {
                        "field": "document_code",
                        "pattern": r"(?P<value>REPORT-[A-Z])",
                    },
                ],
                "name_field": "display_name",
            },
            "fields": {"join_wrapped_lines": True},
            "markdown": {"emit_title_fields": ["document_code"]},
        },
    )
    extractor.validate_profile(profile)
    return profile


class FakePage:
    width = 600
    height = 800

    def __init__(self, words: list[dict[str, float | str]]) -> None:
        self.words = words

    def extract_words(self, **_: object) -> list[dict[str, float | str]]:
        return self.words


class ExtractStructuredPdfTests(unittest.TestCase):
    def test_natural_sort_key_orders_numbered_files(self) -> None:
        names = ["page_10.pdf", "page_2.pdf", "page_1.pdf"]
        self.assertEqual(
            sorted(names, key=extractor.natural_key),
            ["page_1.pdf", "page_2.pdf", "page_10.pdf"],
        )

    def test_page_ranges_support_lists_and_open_ends(self) -> None:
        ranges = extractor.parse_page_spec("1-3,5,8-")
        self.assertTrue(extractor.page_selected(2, ranges))
        self.assertFalse(extractor.page_selected(6, ranges))
        self.assertTrue(extractor.page_selected(20, ranges))

    def test_join_words_preserves_latin_spaces_but_not_chinese_spacing(self) -> None:
        chinese = [word("项目", 0, 20, 0), word("报告", 40, 60, 0)]
        latin = [word("ANNUAL", 0, 45, 0), word("REPORT", 49, 90, 0)]
        self.assertEqual(extractor.join_words(chinese, 0.45), "项目报告")
        self.assertEqual(extractor.join_words(latin, 0.45), "ANNUAL REPORT")

    def test_two_column_page_reads_left_column_before_right(self) -> None:
        profile = extractor.load_profile(None)
        profile["layout"].update(
            {"columns": "2", "top_margin_ratio": 0, "bottom_margin_ratio": 0}
        )
        page = FakePage(
            [
                word("左一", 20, 50, 100),
                word("右一", 330, 360, 100),
                word("左二", 20, 50, 120),
                word("右二", 330, 360, 120),
            ]
        )
        lines, empty = extractor.extract_page_lines(page, Path("sample.pdf"), 1, profile)
        self.assertEqual(empty, 0)
        self.assertEqual([line.text for line in lines], ["左一", "左二", "右一", "右二"])

    def test_sequence_segmentation_and_fields(self) -> None:
        profile = sequence_profile()
        texts = [
            "项目甲",
            "REPORT-A",
            "【负责人】张三",
            "【摘要】第一段，",
            "第二段。",
            "项目乙",
            "REPORT-B",
            "【摘要】另一份摘要。",
        ]
        lines = [extractor.TextLine(text, "sample.pdf", 1, index, 1) for index, text in enumerate(texts)]
        sections, preface_count = extractor.segment_lines(lines, profile)
        extractor.populate_fields(sections, profile)
        self.assertEqual(preface_count, 0)
        self.assertEqual([section.display_name for section in sections], ["项目甲", "项目乙"])
        self.assertEqual(sections[0].fields["摘要"], "第一段，第二段。")

    def test_profile_value_replacements_correct_extracted_titles(self) -> None:
        profile = sequence_profile()
        profile["entry"]["value_replacements"] = {"display_name": {"项目甲": "项目一"}}
        texts = ["项目甲", "REPORT-A"]
        lines = [extractor.TextLine(text, "sample.pdf", 1, index, 1) for index, text in enumerate(texts)]
        sections, _ = extractor.segment_lines(lines, profile)
        self.assertEqual(sections[0].display_name, "项目一")

    def test_merge_uses_named_column_without_rewriting_unmatched_rows(self) -> None:
        profile = sequence_profile()
        line = extractor.TextLine("【摘要】更新后的摘要。", "sample.pdf", 1, 1, 1)
        section = extractor.Section({"display_name": "项目甲"}, [], [line])
        section.normalized_name = "项目甲"
        extractor.populate_fields([section], profile)
        source = extractor.pd.DataFrame({"项目": ["项目甲", "不存在"], "摘要": ["旧值", "保留"]})
        merged, report = extractor.merge_records_into_table(
            source,
            [section],
            "项目",
            [("摘要", "摘要")],
            "error",
            profile["entry"]["normalization"],
        )
        self.assertEqual(merged.loc[0, "摘要"], "更新后的摘要。")
        self.assertEqual(merged.loc[1, "摘要"], "保留")
        self.assertEqual(report["matched_rows"], 1)

    def test_output_paths_cannot_overwrite_an_input_pdf(self) -> None:
        input_pdf = Path("sample.pdf").resolve()
        args = Namespace(
            markdown_output=str(input_pdf),
            records_output=None,
            report_output=None,
            merge_output=None,
            merge_input=None,
            in_place=False,
        )
        with self.assertRaisesRegex(ValueError, "cannot overwrite an input PDF"):
            extractor.validate_output_paths(args, [input_pdf])


if __name__ == "__main__":
    unittest.main()
