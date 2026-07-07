"""
Set up (and check) the Spider2-Snow resources this benchmark needs.

The tasks reference Spider2-Snow **database schemas** and **external-knowledge
documents** by name. These are Spider 2.0 assets and are *not* redistributed here
(the underlying data is access-controlled). You obtain them once from Spider 2.0,
point this repo at them, and then run the benchmark.

This script prints the acquisition steps and reports exactly which resources the
393 tasks need vs. what is present under resources/.

Usage:
    python scripts/setup_resources.py
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("AISQL_PROJECT_ROOT", Path(__file__).parent.parent)).resolve()
TASKS = PROJECT_ROOT / "data" / "spider2-aifunc.jsonl"
DB_DIR = PROJECT_ROOT / "resources" / "databases"
KN_DIR = PROJECT_ROOT / "resources" / "knowledge"

SETUP_STEPS = f"""\
How to set up resources (one time)
----------------------------------
The schemas/knowledge live in the Spider 2.0 repo's `spider2-snow` package, and the
databases themselves are access-controlled Snowflake data. To materialize them:

  1. Request Snowflake access and configure credentials by following Spider 2.0's
     Snowflake guideline:
       https://github.com/xlang-ai/Spider2/blob/main/assets/Snowflake_Guideline.md

  2. Clone Spider 2.0 and run its setup, which materializes the database schema
     files and knowledge docs locally:
       git clone https://github.com/xlang-ai/Spider2.git
       cd Spider2/methods/spider-agent-snow
       pip install -r requirements.txt
       python spider_agent_setup_snow.py

  3. Point this repo at what that produced, either by symlinking:
       mkdir -p {PROJECT_ROOT / "resources"}
       ln -s /path/to/Spider2/spider2-snow/resources/databases {DB_DIR}
       ln -s /path/to/Spider2/spider2-snow/resources/knowledge  {KN_DIR}
     or by copying those two directories to the paths above. You can also set
     AISQL_PROJECT_ROOT to another repo root that contains data/ and resources/.

  4. Re-run this script to confirm everything the tasks need is present.
"""


def main():
    print(SETUP_STEPS)

    if not TASKS.exists():
        print(f"! Task file not found: {TASKS}")
        return

    need_dbs, need_docs = set(), set()
    with open(TASKS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            need_dbs.add(row["db_id"])
            ek = row.get("external_knowledge")
            if ek:
                need_docs.add(ek)

    have_dbs = {p.name for p in DB_DIR.iterdir()} if DB_DIR.exists() else set()
    have_docs = {p.name for p in KN_DIR.iterdir()} if KN_DIR.exists() else set()

    missing_dbs = sorted(need_dbs - have_dbs)
    missing_docs = sorted(need_docs - have_docs)

    print("Status")
    print("------")
    if not DB_DIR.exists():
        print(f"resources/databases not found (expected at {DB_DIR})")
    if not KN_DIR.exists():
        print(f"resources/knowledge not found (expected at {KN_DIR})")
    print(f"Databases : need {len(need_dbs)}, present {len(need_dbs & have_dbs)}, missing {len(missing_dbs)}")
    print(f"Knowledge : need {len(need_docs)}, present {len(need_docs & have_docs)}, missing {len(missing_docs)}")

    if missing_dbs:
        print("\nMissing databases (expected under resources/databases/<DB_ID>/):")
        for d in missing_dbs[:50]:
            print(f"  {d}")
        if len(missing_dbs) > 50:
            print(f"  ... and {len(missing_dbs) - 50} more")
    if missing_docs:
        print("\nMissing knowledge docs (expected under resources/knowledge/<doc>):")
        for d in missing_docs:
            print(f"  {d}")

    if not missing_dbs and not missing_docs:
        print("\nAll required resources are present. You're ready to run.")
    else:
        print("\nComplete the setup steps above, then re-run this check.")


if __name__ == "__main__":
    main()
