import hashlib
import json
from pathlib import Path

import openpyxl
from hamcrest import (
    assert_that,
    close_to,
    contains_inanyorder,
    ends_with,
    equal_to,
    has_length,
    is_,
)

from tickmark.cases import load_case
from tickmark.cell_refs import split_reference
from tickmark.malformed_outputs import (
    find_intermediate_target,
    generate_malformed_outputs,
)
from tickmark.workbook_audit import values_match
from tickmark.workbook_reader import read_workbook


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generates_controlled_bad_outputs_without_changing_golden(tmp_path) -> None:
    case = load_case("data/cases/16_04")
    golden_before = _digest(case.golden_workbook)

    generated = generate_malformed_outputs(case, tmp_path)

    assert_that(generated, has_length(7))
    assert_that(
        [item.variant for item in generated],
        contains_inanyorder(
            "hardcoded_final",
            "hardcoded_half",
            "hardcoded_all",
            "fake_formula_final",
            "wrong_formula_final",
            "broken_reference_final",
            "hardcoded_intermediate",
        ),
    )
    assert_that(_digest(case.golden_workbook), equal_to(golden_before))
    assert_that(all((tmp_path / item.workbook).exists() for item in generated), is_(True))


def test_variants_expose_expected_formula_and_lineage_failures(tmp_path) -> None:
    case = load_case("data/cases/16_04")
    generated = {item.variant: item for item in generate_malformed_outputs(case, tmp_path)}

    hardcoded = read_workbook(tmp_path / generated["hardcoded_final"].workbook)
    assert_that(hardcoded.observations[case.final_output].has_formula, is_(False))
    assert_that(hardcoded.observations[case.final_output].value, equal_to(12150480))

    fake = read_workbook(tmp_path / generated["fake_formula_final"].workbook)
    assert_that(fake.observations[case.final_output].formula, equal_to("=12150480"))
    assert_that(fake.observations[case.final_output].precedents, has_length(0))
    assert_that(generated["fake_formula_final"].expected_formula_coverage, equal_to(1.0))
    assert_that(generated["fake_formula_final"].expected_traceability, close_to(27 / 28, 1e-12))

    wrong = read_workbook(tmp_path / generated["wrong_formula_final"].workbook)
    assert_that(wrong.observations[case.final_output].formula or "", ends_with(")*1.01+1"))
    assert_that(wrong.observations[case.final_output].has_formula, is_(True))
    assert_that(bool(wrong.observations[case.final_output].range_precedents), is_(True))
    assert_that(generated["wrong_formula_final"].expected_traceability, equal_to(1.0))

    broken = read_workbook(tmp_path / generated["broken_reference_final"].workbook)
    assert_that(bool(broken.issues), is_(True))
    assert_that(generated["broken_reference_final"].expected_traceability, close_to(27 / 28, 1e-12))


def test_hardcoding_levels_and_intermediate_are_recorded_in_manifest(tmp_path) -> None:
    case = load_case("data/cases/16_04")
    generated = {item.variant: item for item in generate_malformed_outputs(case, tmp_path)}
    intermediate = find_intermediate_target(case)

    assert_that(generated["hardcoded_half"].mutations, has_length(14))
    assert_that(generated["hardcoded_half"].expected_formula_coverage, equal_to(0.5))
    assert_that(generated["hardcoded_all"].mutations, has_length(28))
    assert_that(generated["hardcoded_all"].expected_formula_coverage, equal_to(0.0))
    assert_that(generated["hardcoded_intermediate"].mutations[0].cell, equal_to(intermediate))
    assert_that(intermediate == case.final_output, is_(False))

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert_that(manifest["case_id"], equal_to("16_04"))
    assert_that(manifest["outputs"], has_length(7))


def test_generated_outputs_preserve_target_cell_styles(tmp_path) -> None:
    case = load_case("data/cases/16_04")
    generated = generate_malformed_outputs(case, tmp_path)
    sheet, address = split_reference(case.final_output)
    golden = openpyxl.load_workbook(case.golden_workbook, data_only=False)
    expected_style = golden[sheet][address]._style

    for item in generated:
        output = openpyxl.load_workbook(tmp_path / item.workbook, data_only=False)
        assert_that(output[sheet][address]._style, equal_to(expected_style), item.variant)


def test_wrong_formula_error_is_outside_every_case_tolerance() -> None:
    # A +1 error hid inside the relative tolerance of outputs in the millions (e.g. 14_07).
    case_dirs = sorted(path.parent for path in Path("data/cases").glob("*/case.json"))

    for case_dir in case_dirs:
        case = load_case(case_dir)
        correct = case.reference_values[case.final_output]
        wrong = correct * 1.01 + 1
        assert_that(
            values_match(
                wrong,
                correct,
                abs_tolerance=case.abs_tolerance,
                rel_tolerance=case.rel_tolerance,
            ),
            is_(False),
            case.case_id,
        )


def test_every_selected_case_has_an_intermediate_target() -> None:
    case_dirs = sorted(
        path.parent for path in __import__("pathlib").Path("data/cases").glob("*/case.json")
    )

    assert_that(case_dirs, has_length(35))
    assert_that(all(find_intermediate_target(load_case(path)) for path in case_dirs), is_(True))
