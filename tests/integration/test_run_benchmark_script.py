import importlib.util
import json
import sys
from pathlib import Path

from hamcrest import assert_that, contains_string, equal_to, is_
from tests.shared.givenpy import given, then, when

ROOT = Path(__file__).resolve().parents[2]


def _run_benchmark_module():
    spec = importlib.util.spec_from_file_location(
        "run_benchmark", ROOT / "scripts" / "run_benchmark.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def test_when_one_workbook_breaks_the_evaluator_then_the_others_are_still_graded(
    tmp_path, monkeypatch
) -> None:
    with given() as context:
        context.script = _run_benchmark_module()
        grade = context.script.evaluate_workbook

        def flaky(case, workbook, engine, **options):
            if case.case_id == "14_07":
                raise RuntimeError("COM server went away")
            return grade(case, workbook, engine, **options)

        monkeypatch.setattr(context.script, "evaluate_workbook", flaky)
        cases = [str(ROOT / "data" / "cases" / name) for name in ("14_07", "16_04")]

    with when():
        context.code = context.script.main(
            ["--case", *cases, "--golden", "--engine", "cached", "--out", str(tmp_path)]
        )

    with then():
        assert_that(context.code, equal_to(3))
        failed = json.loads((tmp_path / "14_07" / "golden.cached.json").read_text("utf-8"))
        assert_that(failed["passed"], is_(None))
        assert_that(failed["error"], contains_string("COM server went away"))
        graded = json.loads((tmp_path / "16_04" / "golden.cached.json").read_text("utf-8"))
        assert_that(graded["correct"], is_(True))
