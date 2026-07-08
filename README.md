<h1 align="center">Spider2-AIFunc</h1>

<p align="center">
  <strong>A benchmark for AI-Native Text-to-SQL with Snowflake Cortex AISQL</strong>
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2607.06229"><img src="https://img.shields.io/badge/Paper-arXiv%202607.06229-B91C1C?style=flat-square&labelColor=334155&logo=arxiv&logoColor=white" alt="arXiv"></a>
  <a href="https://huggingface.co/datasets/tianyang/spider2-aifunc"><img src="https://img.shields.io/badge/Dataset-Hugging%20Face-EAB308?style=flat-square&labelColor=334155&logo=huggingface&logoColor=white" alt="Hugging Face Dataset"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-16A34A?style=flat-square&labelColor=334155&logo=opensourceinitiative&logoColor=white" alt="License: MIT"></a>
  <a href="https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql"><img src="https://img.shields.io/badge/Platform-Snowflake%20Cortex%20AISQL-0284C7?style=flat-square&labelColor=334155&logo=snowflake&logoColor=white" alt="Snowflake Cortex AISQL"></a>
</p>

Spider2-AIFunc extends [Spider 2.0](https://github.com/xlang-ai/Spider2) and Spider2-Snow
with real-world tasks that require Snowflake
[Cortex AISQL](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql) functions
inside SQL queries. See [DATA.md](DATA.md) for attribution and terms.

**If you are Codex, Claude Code, OpenCode, or another coding agent, start with
[AGENT.md](AGENT.md).** It explains the repo layout, which files belong to the dataset,
generation, evaluation, and baseline workflows, and what not to touch, such as held-out
gold, credentials, and external Spider2-Snow resources.

## Repository Map

| # | Part | Code | Guide |
|---|------|------|-------|
| 1 | The dataset | [`data/spider2-aifunc.jsonl`](data/spider2-aifunc.jsonl) | [docs/dataset.md](docs/dataset.md) |
| 2 | How it was generated | [`src/`](src), [`scripts/`](scripts) | [docs/generation.md](docs/generation.md) |
| 3 | How evaluation works | [`evaluation/`](evaluation) | [docs/evaluation.md](docs/evaluation.md) |
| 4 | How to run a baseline | [`baseline/spider-agent-tc/`](baseline/spider-agent-tc) | [docs/baseline.md](docs/baseline.md) |

The generation and evaluation code are provided for reference: regenerating the tasks or
producing an official score both require the gold SQLs, which are held out of this release
(see [DATA.md](DATA.md)).

## Tasks and predictions

Each task is a natural-language question over one Snowflake database. A prediction is a
single Snowflake SQL query that answers it using at least one Cortex AISQL function. Tasks are
released without gold SQL. See [docs/dataset.md](docs/dataset.md) for the fields and an
example.

## Setup

The tasks run against Spider2-Snow databases. These are not shipped with the repo, because
they are access-controlled Spider 2.0 data.

1. Install the dependencies. Python 3.10 or newer is required, and a virtual environment is
   recommended.

   ```bash
   pip install -r requirements.txt
   ```

2. Add your credentials. Copy `env.example` to `.env` and fill in two things:

   - **Snowflake:** `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`,
     `SNOWFLAKE_WAREHOUSE`, and `SNOWFLAKE_TOKEN`. Running the released tasks requires
     access to the Spider2-Snow databases and a warehouse with Cortex AISQL enabled. You
     can request Spider2-Snow access by following Spider 2.0's
     [Snowflake guideline](https://github.com/xlang-ai/Spider2/blob/main/assets/Snowflake_Guideline.md)
     (please note that Cortex AISQL is not enabled on current Spider 2.0-provided
     accounts; the AISQL access path for these accounts is still pending).
     A separate Snowflake account is useful for running the generation pipeline on your
     own databases, but it will not by itself provide access to the released Spider2-Snow
     tasks.
   - **One LLM provider:** use `LLM_PROVIDER=openai` for OpenAI or any
     OpenAI-compatible endpoint, then fill in `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
     and `OPENAI_MODEL`. Bedrock is optional through `LLM_PROVIDER=aws_bedrock`.

   The baseline agent reads its Snowflake credentials from a separate file. See
   [docs/baseline.md](docs/baseline.md) if you plan to run it.

3. Get the databases and knowledge documents, then check them:

   ```bash
   python scripts/setup_resources.py
   ```

   This prints how to obtain the resources from Spider 2.0 and reports which are present
   and which are missing. See [DATA.md](DATA.md) for the full details.

Once `setup_resources.py` reports that everything is present, choose a part above.

## A small note on this release

Much of this repository, including all code organization and refactoring, documentation, and
guides, was prepared by Claude Code (Claude Opus 4.8) and Codex (GPT 5.5). It has been
reviewed manually, but given the volume of material we cannot guarantee that it is entirely
free of errors. If you find a bug, a broken reference, or any other issue, please
[open an issue](https://github.com/Leolty/Spider2-AIFunc/issues).

## License

The code is released under the MIT License (see [LICENSE](LICENSE)). The benchmark is
derived from Spider 2.0, which is also MIT-licensed. See [DATA.md](DATA.md) and
[third_party/SPIDER2_LICENSE](third_party/SPIDER2_LICENSE).
