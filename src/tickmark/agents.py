"""Agent adapters: let a coding agent, a chat model or a person complete a case.

Every agent receives the same ``AgentTask`` (instruction + ``input.xlsx``) and must
produce ``output.xlsx`` in its workspace:

- ``CliAgent`` runs a command-line coding agent (Claude Code, Gemini CLI, ...) in
  a folder that holds only ``input.xlsx`` and ``TASK.md``;
- ``ChatAgent`` sends the workbook as text to any OpenAI-compatible chat API
  (Gemini, OpenRouter, Groq, Ollama, ...) and writes the JSON cell edits it returns;
- ``ManualAgent`` prepares the task for a person using a chat UI and picks up the
  ``output.xlsx`` they save later.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import openpyxl

from .workbook_prompt import apply_cell_edits, describe_workbook, parse_cell_edits

INPUT_NAME = "input.xlsx"
OUTPUT_NAME = "output.xlsx"
TASK_NAME = "TASK.md"
SHORT_PROMPT = f"Read {TASK_NAME} in the current directory and complete the task it describes."
_LOG_TAIL = 20_000

_CLI_WORKBOOK_PROTOCOL = """## Workbook execution protocol

Use Python with `openpyxl` to inspect and edit the workbook. Do not unzip the
workbook or inspect its raw XML/package files. Read only the task's target
sheet and the nearby cells needed to infer the formula pattern.

Edit only the requested target cells. Use live Excel formulas, preserving the
existing workbook structure and formatting. Save `output.xlsx` before any
optional checking, then reopen it with `openpyxl` and confirm that it exists
and each requested target cell contains a formula. Do not use web tools, Excel,
LibreOffice, or external applications.
"""


@dataclass(frozen=True)
class AgentTask:
    """One case as an agent sees it; ``workspace`` is where ``output.xlsx`` must appear."""

    case_id: str
    instruction: str
    input_workbook: Path
    workspace: Path
    task_markdown: str | None = None


@dataclass(frozen=True)
class AgentResult:
    """``status`` is ``completed``, ``no_output``, ``failed`` or ``pending`` (manual agents)."""

    status: str
    output_workbook: Path | None
    duration_seconds: float = 0.0
    log: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Agent(Protocol):
    name: str
    kind: str

    def solve(self, task: AgentTask) -> AgentResult:
        """Complete ``task`` and return where the completed workbook is."""
        ...


def task_text(task: AgentTask) -> str:
    if task.task_markdown is not None:
        return task.task_markdown
    return (
        f"# Task {task.case_id}\n\n"
        f"The Excel workbook `{INPUT_NAME}` is in this folder.\n\n"
        f"{task.instruction}\n\n"
        f"{_CLI_WORKBOOK_PROTOCOL}\n"
        f"Save the completed workbook as `{OUTPUT_NAME}` in this folder. Keep every sheet, "
        "label and existing cell where it is.\n"
    )


def prepare_workspace(task: AgentTask) -> None:
    """Put ``input.xlsx`` and ``TASK.md`` in the workspace (existing files are kept)."""

    task.workspace.mkdir(parents=True, exist_ok=True)
    if not (task.workspace / INPUT_NAME).exists():
        shutil.copy2(task.input_workbook, task.workspace / INPUT_NAME)
    if not (task.workspace / TASK_NAME).exists():
        (task.workspace / TASK_NAME).write_text(task_text(task), encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tail(text: str | None) -> str:
    return (text or "")[-_LOG_TAIL:]


def _natural_key(path: str) -> list[Any]:
    """Sort ``2.1.99`` before ``2.1.266`` (numbers compared as numbers)."""

    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path)]


def resolve_executable(name: str, fallbacks: Sequence[str] = ()) -> str | None:
    """Find ``name`` on PATH, else the newest match of the fallback glob patterns."""

    found = shutil.which(name)
    if found:
        return found
    for pattern in fallbacks:
        matches = glob.glob(os.path.expandvars(os.path.expanduser(pattern)))
        if matches:
            return max(matches, key=_natural_key)
    return None


class CliAgent:
    """Run a command-line coding agent in an isolated workspace.

    ``command`` is an argument list; ``{prompt}`` is replaced by a one-line prompt
    telling the agent to read ``TASK.md``. The agent's own tools edit the workbook.
    """

    kind = "cli"

    def __init__(
        self,
        name: str,
        command: Sequence[str],
        *,
        timeout: float = 900.0,
        fallback_paths: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.name = name
        self.command = list(command)
        self.timeout = timeout
        self.fallback_paths = list(fallback_paths)
        self.env = dict(env or {})

    def solve(self, task: AgentTask) -> AgentResult:
        prepare_workspace(task)
        executable = resolve_executable(self.command[0], self.fallback_paths)
        if executable is None:
            return AgentResult("failed", None, error=f"executable {self.command[0]!r} not found")
        args = [executable, *(part.replace("{prompt}", SHORT_PROMPT) for part in self.command[1:])]
        input_copy = task.workspace / INPUT_NAME
        before = _digest(input_copy)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                cwd=task.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env={**os.environ, **self.env},
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return AgentResult(
                "failed",
                None,
                time.monotonic() - started,
                {"command": args, "stdout_tail": _tail(str(error.stdout or ""))},
                f"timed out after {self.timeout:.0f}s",
            )
        duration = time.monotonic() - started
        log: dict[str, Any] = {
            "command": args,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        }
        try:
            log["stdout_json"] = json.loads(completed.stdout)  # e.g. claude --output-format json
        except json.JSONDecodeError, TypeError:
            pass

        output = task.workspace / OUTPUT_NAME
        if not output.exists() and _digest(input_copy) != before:
            output = input_copy  # the agent edited input.xlsx in place
            log["note"] = f"no {OUTPUT_NAME}; graded the edited {INPUT_NAME}"
        if not output.exists():
            if completed.returncode != 0:
                reason = _agent_error(log) or f"exit code {completed.returncode}"
                return AgentResult("failed", None, duration, log, f"agent failed: {reason}")
            return AgentResult("no_output", None, duration, log, f"no {OUTPUT_NAME} produced")
        return AgentResult("completed", output, duration, log)


def _agent_error(log: Mapping[str, Any]) -> str | None:
    """The agent's own error: a JSON ``result`` flagged as error, else stderr's last line."""

    parsed = log.get("stdout_json")
    if isinstance(parsed, dict) and parsed.get("is_error") and parsed.get("result"):
        return str(parsed["result"])
    lines = [line for line in str(log.get("stderr_tail", "")).splitlines() if line.strip()]
    return lines[-1] if lines else None


SYSTEM_PROMPT = """You complete financial models in Excel workbooks. You cannot run code or \
open files. The workbook is shown as one line per non-empty cell: `C7: 58` is a value, \
`G7: =SUM(C7:F7)` is a formula; `[= 320]` after a formula is its saved result, when the file \
has one.

Reply with a single JSON object and nothing else:
{"cells": {"Sheet!C17": "=C7*C10*12", "Sheet!D17": 1234}}
List every cell you fill. Formulas are strings starting with "=" in Excel syntax; numbers \
are JSON numbers."""

Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class ChatAgent:
    """Use any OpenAI-compatible ``/chat/completions`` endpoint as a spreadsheet agent.

    The model sees the instruction plus a text view of ``input.xlsx`` and answers
    with JSON cell edits, which are written into a copy saved as ``output.xlsx``.
    An unusable reply gets ``repair_attempts`` follow-up messages explaining why.
    """

    kind = "chat"

    def __init__(
        self,
        name: str,
        *,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        api_key_optional: bool = False,
        timeout: float = 300.0,
        temperature: float | None = 0.0,
        repair_attempts: int = 1,
        http_retries: int = 5,
        max_retry_wait: float = 60.0,
        extra_body: Mapping[str, Any] | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.api_key_optional = api_key_optional
        self.timeout = timeout
        self.temperature = temperature
        self.repair_attempts = repair_attempts
        self.http_retries = http_retries
        self.max_retry_wait = max_retry_wait
        self.extra_body = dict(extra_body or {})
        self._transport = transport or _post_json
        self._sleep = sleep

    def _complete(self, messages: list[dict[str, str]], headers: dict[str, str]) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, **self.extra_body}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        url = f"{self.base_url}/chat/completions"
        for attempt in range(self.http_retries + 1):
            try:
                return self._transport(url, payload, headers, self.timeout)
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == self.http_retries:
                    body = error.read().decode("utf-8", errors="replace")[:2000]
                    raise RuntimeError(f"HTTP {error.code} from {url}: {body}") from error
                self._sleep(self._retry_wait(error, attempt))
        raise AssertionError("unreachable")

    def _retry_wait(self, error: urllib.error.HTTPError, attempt: int) -> float:
        """Seconds before the next try: the server's ``Retry-After``, else exponential.

        Rate limits (429) start at 5 s, since free tiers often need tens of seconds;
        server errors start at 1 s. Both are capped at ``max_retry_wait``.
        """

        retry_after = (error.headers or {}).get("Retry-After", "")
        if str(retry_after).strip().isdigit():
            return min(float(retry_after), self.max_retry_wait)
        first = 5.0 if error.code == 429 else 1.0
        return min(first * 2**attempt, self.max_retry_wait)

    def solve(self, task: AgentTask) -> AgentResult:
        task.workspace.mkdir(parents=True, exist_ok=True)
        headers: dict[str, str] = {}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
            elif not self.api_key_optional:
                return AgentResult(
                    "failed", None, error=f"environment variable {self.api_key_env} is not set"
                )

        sheets = openpyxl.load_workbook(task.input_workbook, read_only=True).sheetnames
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{task.instruction}\n\n{describe_workbook(task.input_workbook)}",
            },
        ]
        log: dict[str, Any] = {"model": self.model, "base_url": self.base_url, "exchanges": []}
        started = time.monotonic()
        edits: dict[str, Any] | None = None
        error: str | None = None
        for _ in range(self.repair_attempts + 1):
            try:
                response = self._complete(messages, headers)
            except (RuntimeError, OSError, ValueError) as failure:  # HTTP, network, bad JSON
                return AgentResult("failed", None, time.monotonic() - started, log, str(failure))
            choice = (response.get("choices") or [{}])[0]
            reply = str((choice.get("message") or {}).get("content") or "")
            log["exchanges"].append({"reply": _tail(reply), "usage": response.get("usage")})
            try:
                edits = parse_cell_edits(reply, sheets[0])
                break
            except ValueError as problem:
                error = str(problem)
                messages += [
                    {"role": "assistant", "content": reply},
                    {
                        "role": "user",
                        "content": f"Your reply could not be used: {problem}. "
                        "Reply with the JSON object only.",
                    },
                ]
        duration = time.monotonic() - started
        if edits is None:
            return AgentResult("no_output", None, duration, log, f"unusable reply: {error}")
        output = task.workspace / OUTPUT_NAME
        skipped = apply_cell_edits(task.input_workbook, edits, output)
        log.update({"cells_written": len(edits) - len(skipped), "skipped_edits": skipped})
        return AgentResult("completed", output, duration, log)


class ManualAgent:
    """A person solves the task elsewhere (ChatGPT, Excel Copilot...) and saves ``output.xlsx``.

    The runner uses the case's result folder as the workspace, so ``TASK.md`` and
    ``input.xlsx`` land there; re-running grades the workbook once it exists.
    """

    kind = "manual"

    def __init__(self, name: str) -> None:
        self.name = name

    def solve(self, task: AgentTask) -> AgentResult:
        prepare_workspace(task)
        output = task.workspace / OUTPUT_NAME
        if output.exists():
            return AgentResult("completed", output)
        return AgentResult(
            "pending",
            None,
            log={"instructions": f"Solve {TASK_NAME} and save {OUTPUT_NAME} in {task.workspace}"},
        )


def build_agent(name: str, settings: Mapping[str, Any]) -> Agent:
    kind = settings.get("type")
    if kind == "cli":
        return CliAgent(
            name,
            settings["command"],
            timeout=float(settings.get("timeout", 900)),
            fallback_paths=settings.get("fallback_paths", []),
            env=settings.get("env"),
        )
    if kind == "chat":
        return ChatAgent(
            name,
            base_url=settings["base_url"],
            model=settings["model"],
            api_key_env=settings.get("api_key_env") or None,
            api_key_optional=bool(settings.get("api_key_optional", False)),
            timeout=float(settings.get("timeout", 300)),
            temperature=settings.get("temperature", 0.0),
            repair_attempts=int(settings.get("repair_attempts", 1)),
            http_retries=int(settings.get("http_retries", 5)),
            max_retry_wait=float(settings.get("max_retry_wait", 60)),
            extra_body=settings.get("extra_body"),
        )
    if kind == "manual":
        return ManualAgent(name)
    raise ValueError(f"agent {name!r}: unknown type {kind!r} (expected cli, chat or manual)")


def load_agents(config: Path, names: Sequence[str] | None = None) -> list[Agent]:
    """Build agents from a TOML file with one ``[agents.<name>]`` table per agent.

    A name may also be ``<provider>:<model>`` for any ``[providers.<provider>]`` table,
    e.g. ``openrouter:z-ai/glm-5.2:free``; the agent is then named ``agent_slug(name)``.
    """

    settings = agent_settings(config, names or list(load_agent_table(config)))
    return [build_agent(agent_slug(name), entry) for name, entry in settings.items()]


def load_agent_table(config: Path) -> dict[str, dict[str, Any]]:
    """The ``[agents.<name>]`` tables of a config file, by agent name."""

    return tomllib.loads(config.read_text(encoding="utf-8")).get("agents", {})


def load_providers(config: Path) -> dict[str, dict[str, Any]]:
    """The ``[providers.<name>]`` tables: OpenAI-compatible endpoints serving many models."""

    return tomllib.loads(config.read_text(encoding="utf-8")).get("providers", {})


def agent_settings(config: Path, names: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Settings for each name: its ``[agents.<name>]`` table, or a chat agent for a
    ``<provider>:<model>`` spec built from ``[providers.<provider>]``."""

    agents, providers = load_agent_table(config), load_providers(config)
    found: dict[str, dict[str, Any]] = {}
    unknown = []
    for name in names:
        provider, _, model = name.partition(":")
        if name in agents:
            found[name] = agents[name]
        elif model and provider in providers:
            found[name] = provider_agent(providers[provider], model)
        else:
            unknown.append(name)
    if unknown:
        raise ValueError(
            f"unknown agent(s) {unknown}; configured: {sorted(agents)}; "
            f"or use <provider>:<model> with a provider from {sorted(providers)}"
        )
    return found


def provider_agent(provider: Mapping[str, Any], model: str) -> dict[str, Any]:
    """A chat agent's settings for ``model`` served by ``provider``."""

    return {
        "type": "chat",
        "base_url": provider["base_url"],
        "model": model,
        "api_key_env": provider.get("api_key_env"),
        "api_key_optional": provider.get("api_key_optional", False),
        "timeout": provider.get("timeout", 600),
        "setup": provider.get("setup"),
    }


def agent_slug(name: str) -> str:
    """A folder-safe agent name.

    ``openrouter:z-ai/glm-5.2:free`` becomes ``openrouter-z-ai-glm-5.2-free``.
    """

    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "agent"


def load_env_file(path: Path) -> list[str]:
    """Set ``KEY=value`` lines from ``path`` unless the variable is already set.

    Returns the names set (values are never shown). Blank lines, ``#`` comments and an
    ``export`` prefix are allowed, and quotes around a value are removed. UTF-16 files, as
    Windows PowerShell 5 writes with ``>``, are read too.
    """

    if not path.is_file():
        return []
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    loaded = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


@dataclass(frozen=True)
class Readiness:
    """Whether an agent can start on this machine; ``setup`` says what to do if not."""

    ready: bool
    detail: str
    setup: str | None = None


def check_agent(settings: Mapping[str, Any]) -> Readiness:
    """Check an ``[agents.<name>]`` table without running the agent.

    A CLI agent needs its executable (on PATH or a fallback path) and a chat agent the
    API key named by ``api_key_env``, if any. Whether a CLI is signed in only shows when
    it runs, so ``setup`` mentions the sign-in step too.
    """

    setup = settings.get("setup")
    kind = settings.get("type")
    if kind == "cli":
        program = (settings.get("command") or ["?"])[0]
        found = resolve_executable(program, settings.get("fallback_paths", []))
        if found is None:
            return Readiness(False, f"{program} not found", setup)
        return Readiness(True, found, setup)
    if kind == "chat":
        key = settings.get("api_key_env")
        if key and not os.environ.get(key) and not settings.get("api_key_optional"):
            return Readiness(False, f"{key} is not set", setup)
        return Readiness(True, f"{settings.get('model')} at {settings.get('base_url')}", setup)
    if kind == "manual":
        return Readiness(True, f"you solve {TASK_NAME} in a chat UI", setup)
    return Readiness(False, f"unknown type {kind!r} (expected cli, chat or manual)", setup)
