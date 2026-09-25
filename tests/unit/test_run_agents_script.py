import importlib.util
import sys
from pathlib import Path

from hamcrest import assert_that, contains_string, equal_to
from tests.shared.givenpy import given, then, when

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _run_agents():
    spec = importlib.util.spec_from_file_location("run_agents", SCRIPTS / "run_agents.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_agents"] = module
    spec.loader.exec_module(module)
    return module


def test_when_an_agent_is_not_ready_then_the_run_stops_before_any_case(tmp_path, capsys) -> None:
    with given() as context:
        context.config = tmp_path / "agents.toml"
        context.config.write_text(
            '[agents.missing]\ntype = "cli"\ncommand = ["no-such-agent", "{prompt}"]\n'
            'setup = "install no-such-agent"\n',
            encoding="utf-8",
        )
        context.results = tmp_path / "runs"

    with when():
        context.code = _run_agents().main(
            [
                "--agents",
                "missing",
                "--config",
                str(context.config),
                "--results",
                str(context.results),
            ]
        )

    with then():
        assert_that(context.code, equal_to(2))
        assert_that(context.results.exists(), equal_to(False))
        error = capsys.readouterr().err
        assert_that(error, contains_string("missing is not ready: no-such-agent not found."))
        assert_that(error, contains_string("setup: install no-such-agent"))


def test_when_agents_are_listed_then_each_shows_whether_it_is_ready(tmp_path, capsys) -> None:
    with given() as context:
        context.config = tmp_path / "agents.toml"
        context.config.write_text(
            f'[agents.here]\ntype = "cli"\ncommand = [{str(sys.executable)!r}, "{{prompt}}"]\n'
            '[agents.person]\ntype = "manual"\n',
            encoding="utf-8",
        )

    with when():
        context.code = _run_agents().main(["--list", "--config", str(context.config)])

    with then():
        assert_that(context.code, equal_to(0))
        out = capsys.readouterr().out
        assert_that(out, contains_string("here"))
        assert_that(out, contains_string("ready"))
        assert_that(out, contains_string("person"))
