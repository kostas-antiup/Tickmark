# Running agents

Tickmark gives an AI agent the same thing a human analyst would get, an Excel template
and a task, then grades the workbook it returns. Agents are defined in
[`configs/agents.toml`](../configs/agents.toml); there are three kinds.

| Type | How the agent works |
|---|---|
| `cli` | A command-line coding agent runs in an empty temporary folder that holds only `input.xlsx` and `TASK.md`, uses its own tools and saves `output.xlsx`. |
| `chat` | Any OpenAI-compatible `/chat/completions` API. The model receives the instruction and the workbook as text (one line per cell) and replies with JSON cell edits, which are written into a copy of `input.xlsx`. |
| `manual` | For chat UIs. You get `TASK.md` and `input.xlsx` in a run folder, do the task yourself in ChatGPT or Excel Copilot, and save `output.xlsx` back there. |

## Quick start

1. **See which agents can run on this machine.**

   ```bash
   uv run python scripts/run_agents.py --list
   ```

   Each agent shows `ready` or `not ready` with the one-line setup step it still needs.

2. **Set one up** with the table below. The quickest free option needs no account:
   install [Ollama](https://ollama.com/download) and run `ollama pull qwen2.5:7b`.

3. **Run the three-case pilot** (`02_01`, `06_18`, `14_07`) and open the report.

   ```bash
   uv run python scripts/run_real_agent_suite.py --agents ollama-qwen --run-id first-run
   ```

   Results land in `results/runs/first-run/`; open `report.html` in a browser.

## Set up an agent

| Agent | Type | Install | Sign in or key |
|---|---|---|---|
| `claude-code` | cli | `npm install -g @anthropic-ai/claude-code`, or the copy bundled with the Claude desktop app (found automatically on Windows) | run `claude` once and type `/login` |
| `codex` | cli | `npm install -g @openai/codex` | run `codex` once to sign in with ChatGPT, or set `OPENAI_API_KEY` |
| `opencode` | cli | `npm install -g opencode-ai` | `opencode auth login` with an OpenCode Zen account (uses `opencode/glm-5.2`) |
| `gemini-cli` | cli | `npm install -g @google/gemini-cli` | run `gemini` once to sign in with Google, or set `GEMINI_API_KEY` |
| `gemini-flash`, `gemini-pro` | chat | nothing | `GEMINI_API_KEY`, free from [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `openrouter-free` | chat | nothing | `OPENROUTER_API_KEY` from [OpenRouter](https://openrouter.ai/keys) |
| `groq-llama` | chat | nothing | `GROQ_API_KEY` from [Groq](https://console.groq.com/keys) |
| `ollama-qwen` | chat | [Ollama](https://ollama.com/download), then `ollama pull qwen2.5:7b` (about 4.7 GB) | none; runs locally |
| `chatgpt-manual`, `excel-copilot-manual` | manual | nothing | none; you do the task |

The `npm` installs need [Node.js](https://nodejs.org). Set API keys in the terminal you run
Tickmark from; they are read from the environment and never stored in the repository.

```powershell
# Windows PowerShell: this terminal only
$env:GEMINI_API_KEY = "your-key"
# ...or for every new terminal
setx GEMINI_API_KEY "your-key"
```

```bash
# macOS and Linux
export GEMINI_API_KEY="your-key"
```

Run `--list` again; the agent should now show `ready`. `run_agents.py` also checks every
agent before a run starts and stops with the setup step if one is not ready.

## Run

```bash
# The three-case pilot for one or more agents
uv run python scripts/run_real_agent_suite.py --agents codex ollama-qwen --run-id pilot

# Chosen cases, or every case (the default is all 35)
uv run python scripts/run_agents.py --agents codex --cases data/cases/14_07 data/cases/06_18 --run-id try
uv run python scripts/run_agents.py --agents codex --run-id full

# Rebuild the summary and report of an existing run
uv run python scripts/run_agents.py --summarize results/runs/full
```

- **Resume:** re-running the same `--run-id` skips cases that already have a report, so a
  run stopped by a rate limit or a closed laptop continues where it stopped. `--rerun`
  redoes them.
- **Engine:** grading uses Microsoft Excel when it is installed, else LibreOffice
  (`--engine excel|libreoffice` to choose).
- **Diagnosis:** `--sensitivity` names the inputs behind each perturbation failure
  ([methodology](methodology.md#per-input-diagnosis)).

## Outputs

Each run writes `results/runs/<run-id>/<agent>/<case>/` with `output.xlsx`,
`agent_log.json` and `report.json`, plus these files for the run:

- `summary.md` and `summary.json`: value-only grading (all numbers correct, as
  answer-matching benchmarks score) next to Tickmark's verdict, and why each case failed.
- `report.html`: one self-contained page in the AAI Labs style, fonts and logo embedded,
  ready to share. It shows the gap between right numbers and real models per agent, the
  outcome mix, heatmaps of checks, model types and sizes, and every case with its main
  issue.

If grading fails, for example because the engine crashes, the case is logged with the
error and the run continues; the next run of the same `--run-id` grades that workbook
again without re-running the agent.

## Manual agents

For assistants without an API or CLI, such as ChatGPT in the browser or Copilot in Excel:

1. `uv run python scripts/run_agents.py --agents chatgpt-manual --cases data/cases/14_07 --run-id manual`
2. Open `results/runs/manual/chatgpt-manual/14_07/`. Give the assistant `TASK.md` and
   `input.xlsx`, or open the workbook in Excel and follow `TASK.md` with Copilot.
3. Save the finished workbook in that folder as `output.xlsx`.
4. Run the command from step 1 again to grade it.

## Add your own agent

Any command-line agent or OpenAI-compatible endpoint takes one table in
`configs/agents.toml`:

```toml
[agents.my-cli-agent]
type = "cli"
command = ["my-agent", "--non-interactive", "{prompt}"]  # {prompt} = "Read TASK.md ..."
timeout = 900
setup = "how to install and sign in, shown by --list"

[agents.my-chat-model]
type = "chat"
base_url = "https://api.example.com/v1"   # any /chat/completions endpoint
model = "model-id"
api_key_env = "MY_API_KEY"                # leave out for local servers
setup = "how to get a key, shown by --list"
```

A CLI agent must leave `output.xlsx` in its working folder (an edited `input.xlsx` is also
accepted). `fallback_paths` lists glob patterns to try when the command is not on `PATH`,
and `env` sets extra environment variables for the agent only.

## Troubleshooting

| Message | Fix |
|---|---|
| `not ready: <program> not found` | Install it, open a new terminal so `PATH` updates, or add its location to `fallback_paths`. |
| `not ready: <KEY> is not set` | Set the key in the same terminal that runs Tickmark, then check `--list`. |
| `agent failed: Not logged in · Please run /login` | Run `claude` once and type `/login`. Other CLIs: sign in once as the table above shows. |
| `HTTP 404 ... model ... not found` (Ollama) | `ollama pull qwen2.5:7b`. |
| Large cases cut off with Ollama | Ollama picks the context length from GPU memory (4k tokens on 8 GB). Set `OLLAMA_CONTEXT_LENGTH=16384` and restart Ollama. |
| `timed out after 900s` | Raise `timeout` for that agent in `configs/agents.toml`. |
| `HTTP 429` | Rate limit: requests are retried with backoff; re-run the same `--run-id` later to continue. |
| No Excel and `soffice` not found | Install LibreOffice, or grade on a machine with Excel. |

## One-off solving

To have an agent fill one case without grading or summaries:

```bash
uv run python scripts/solve_case.py --agent ollama-qwen --case data/cases/02_01
uv run python scripts/solve_case.py --agent claude-code --case data/cases/14_07 --output fixed.xlsx
```

## Isolation

`cli` agents run in a temporary folder outside the repository with restricted tools
(Claude Code and OpenCode are limited to file edits and Python), but they still run on
your machine with your user rights. Use a container for untrusted agents. Chat models see
only the workbook text.
