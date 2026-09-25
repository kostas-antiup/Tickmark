# BlueFin local files

This folder is for a local BlueFin checkout or materialized BlueFin release
files. The downloaded benchmark files are ignored by Git.

Links:

- Repository: <https://github.com/Longitude-Labs/bluefin>
- Hugging Face data release: <https://huggingface.co/datasets/Longitude-Labs/bluefin-release>

The easiest supported layout is a direct clone:

```bash
git clone https://github.com/Longitude-Labs/bluefin data/bluefin
cd data/bluefin
uv sync
cd ../..
```

Then list the synthesis tasks from this repository:

```bash
uv run python scripts/run_bluefin.py --bluefin-root data/bluefin --list
```

Grading uses BlueFin's own agentic judge through `scoring.grade`. It needs the
BlueFin dependencies installed in the BlueFin checkout and the judge model's API
key in the environment, for example `OPENAI_API_KEY` when using the default
`--judge-model gpt-5.4`.
