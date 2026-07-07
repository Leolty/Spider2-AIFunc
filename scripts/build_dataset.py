#!/usr/bin/env python
"""
Build the internal curated benchmark dataset from verified outputs.

This is reference/release-preparation code, not required for running the public
task file. It needs the held-out Spider2 gold data and verified generation
outputs, which are not shipped in this repository.

Assembles data from:
  - Original Spider2 gold data (data/raw/spider2-snow-gold-full.jsonl)
  - Generation outputs (outputs/multi_full/)
  - Final verified outputs (outputs/multi_full_verified_final_r3/)

Drops instances that:
  - Were not "pass" in the final verification round
  - Had AI functions removed by the determinism checker

Usage:
    # Build an internal main dataset from your own generation and verification outputs.
    python scripts/build_dataset.py \
        --original-data data/raw/spider2-snow-gold-full.jsonl \
        --generation-dir outputs/multi_full \
        --verified-dir outputs/multi_full_verified_final_r3

    # Append diversity instances (dedup against main).
    python scripts/build_dataset.py \
        --original-data data/raw/spider2-snow-gold-full.jsonl \
        --generation-dir outputs/multi_full_diversity \
        --verified-dir outputs/multi_full_diversity_verified_final_r3 \
        --variant diversity --suffix _div --append \
        --dedup-verified-dir outputs/multi_full_verified_final_r3
"""
import sys
import json
import shutil
import argparse
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

AI_FUNCS = ['AI_AGG', 'AI_CLASSIFY', 'AI_SIMILARITY', 'AI_FILTER', 'AI_EXTRACT', 'AI_SENTIMENT']


def find_ai_funcs(sql: str) -> list:
    """Find all AI functions used in SQL."""
    sql_upper = sql.upper()
    return sorted([f for f in AI_FUNCS if f in sql_upper])


def parse_args():
    parser = argparse.ArgumentParser(description="Build curated benchmark dataset")
    parser.add_argument(
        "--output-dir", type=str, default="benchmark_dataset",
        help="Output directory for the curated dataset (default: benchmark_dataset)"
    )
    parser.add_argument(
        "--generation-dir", type=str, default="outputs/multi_full",
        help="Generation outputs directory"
    )
    parser.add_argument(
        "--verified-dir", type=str, default="outputs/multi_full_verified_final_r3",
        help="Final verified outputs directory"
    )
    parser.add_argument(
        "--original-data", type=str, default="data/raw/spider2-snow-gold-full.jsonl",
        help="Original Spider2 gold data JSONL"
    )
    parser.add_argument(
        "--variant", type=str, default="main",
        choices=["main", "diversity"],
        help="Variant label (main or diversity)"
    )
    parser.add_argument(
        "--suffix", type=str, default="",
        help="Suffix to append to instance directory names (e.g., '_div' for diversity)"
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append to existing dataset (merge into existing index.json)"
    )
    parser.add_argument(
        "--dedup-verified-dir", type=str, default=None,
        help="Verified dir to dedup against: skip if this variant's AI funcs ⊆ the other's"
    )
    parser.add_argument(
        "--all-verified-dirs", type=str, nargs='+', default=None,
        help="All verification round dirs (phase1, final, r2, r3) to aggregate full verification history"
    )
    return parser.parse_args()


def _build_verification_info(iid: str, final_det_check: dict, all_verified_dirs: list) -> dict:
    """Aggregate verification history across all rounds."""
    if not all_verified_dirs:
        return {
            "status": final_det_check.get('status', ''),
            "num_rounds": final_det_check.get('num_rounds', 0),
            "issues_found": final_det_check.get('issues_found', [])
        }

    rounds_history = []
    total_rounds = 0
    all_issues = []
    for vdir in all_verified_dirs:
        check_path = vdir / iid / 'determinism_check.json'
        if not check_path.exists():
            continue
        with open(check_path) as f:
            check = json.load(f)
        status = check.get('status', '')
        nr = check.get('num_rounds', 0)
        total_rounds += nr
        issues = check.get('issues_found', [])
        for iss in issues:
            if iss not in all_issues:
                all_issues.append(iss)
        rounds_history.append({
            "dir": vdir.name,
            "status": status,
            "num_rounds": nr,
            "sql_changed": check.get('sql_changed', False),
            "instruction_changed": check.get('instruction_changed', False),
        })

    return {
        "status": final_det_check.get('status', ''),
        "total_rounds": total_rounds,
        "issues_found": all_issues,
        "rounds_history": rounds_history
    }


def main():
    args = parse_args()

    # Resolve paths
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    generation_dir = Path(args.generation_dir)
    if not generation_dir.is_absolute():
        generation_dir = PROJECT_ROOT / generation_dir

    verified_dir = Path(args.verified_dir)
    if not verified_dir.is_absolute():
        verified_dir = PROJECT_ROOT / verified_dir

    original_data_path = Path(args.original_data)
    if not original_data_path.is_absolute():
        original_data_path = PROJECT_ROOT / original_data_path

    variant = args.variant
    suffix = args.suffix
    append = args.append

    all_verified_dirs = []
    if args.all_verified_dirs:
        for d in args.all_verified_dirs:
            p = Path(d)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            all_verified_dirs.append(p)

    dedup_verified_dir = None
    if args.dedup_verified_dir:
        dedup_verified_dir = Path(args.dedup_verified_dir)
        if not dedup_verified_dir.is_absolute():
            dedup_verified_dir = PROJECT_ROOT / dedup_verified_dir

    # ── Load original Spider2 data ──────────────────────────────────────
    print("Loading original Spider2 data...")
    original_data = {}
    with open(original_data_path) as f:
        for line in f:
            d = json.loads(line)
            original_data[d['instance_id']] = d
    print(f"  Loaded {len(original_data)} instances")

    # ── Load verified results ───────────────────────────────────────────
    print("Loading verified results...")
    verified_summary = {}
    summary_path = verified_dir / 'check_summary.jsonl'
    with open(summary_path) as f:
        for line in f:
            d = json.loads(line)
            verified_summary[d['instance_id']] = d
    print(f"  Loaded {len(verified_summary)} verified results")

    # ── Determine eligible instances ────────────────────────────────────
    print("\nFiltering instances...")

    passed = {iid for iid, d in verified_summary.items() if d['status'] == 'pass'}
    print(f"  Passed: {len(passed)}")

    # Check for AI function removals
    ai_removed = set()
    for iid in passed:
        gen_sql_path = generation_dir / iid / 'final.sql'
        ver_sql_path = verified_dir / iid / 'final.sql'
        if not gen_sql_path.exists() or not ver_sql_path.exists():
            continue
        gen_funcs = set(find_ai_funcs(gen_sql_path.read_text()))
        ver_funcs = set(find_ai_funcs(ver_sql_path.read_text()))
        if gen_funcs - ver_funcs:
            ai_removed.add(iid)
            print(f"    ✗ {iid}: AI functions removed {gen_funcs - ver_funcs}")

    eligible = sorted(passed - ai_removed)
    dropped_not_pass = len(verified_summary) - len(passed)
    dropped_ai = len(ai_removed)

    print(f"\n  Eligible (before dedup): {len(eligible)}")
    print(f"  Dropped (not pass): {dropped_not_pass}")
    print(f"  Dropped (AI removed): {dropped_ai}")

    # ── Dedup against another verified dir ───────────────────────────────
    dedup_dropped = set()
    if dedup_verified_dir:
        print(f"\n  Dedup against: {dedup_verified_dir}")
        for iid in eligible:
            other_sql_path = dedup_verified_dir / iid / 'final.sql'
            this_sql_path = verified_dir / iid / 'final.sql'
            if other_sql_path.exists() and this_sql_path.exists():
                other_funcs = set(find_ai_funcs(other_sql_path.read_text()))
                this_funcs = set(find_ai_funcs(this_sql_path.read_text()))
                if this_funcs <= other_funcs:  # this variant's funcs are a subset
                    dedup_dropped.add(iid)
        eligible = sorted(set(eligible) - dedup_dropped)
        print(f"    Dropped (AI funcs ⊆ other): {len(dedup_dropped)}")

    print(f"\n  Eligible (final): {len(eligible)}")
    print(f"  Total dropped: {dropped_not_pass + dropped_ai + len(dedup_dropped)}")

    # ── Build dataset ───────────────────────────────────────────────────
    print(f"\nBuilding dataset → {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = Counter()
    index_entries = []

    for iid in eligible:
        orig = original_data.get(iid)
        if not orig:
            print(f"  ⚠ {iid}: not found in original data, skipping")
            stats['missing_original'] += 1
            continue

        dir_name = f"{iid}{suffix}"
        inst_dir = output_dir / dir_name
        inst_dir.mkdir(parents=True, exist_ok=True)

        # ── Read source files ───────────────────────────────────────
        ver_inst_dir = verified_dir / iid
        gen_inst_dir = generation_dir / iid

        ver_sql = (ver_inst_dir / 'final.sql').read_text()
        ver_metadata = json.loads((ver_inst_dir / 'metadata.json').read_text())

        # ── Gold SQL files ──────────────────────────────────────────
        gold_sqls = orig.get('gold_sqls', [])
        for idx, sql in enumerate(gold_sqls):
            label = chr(ord('a') + idx)  # a, b, c, ...
            (inst_dir / f'gold_{label}.sql').write_text(sql)

        # ── AI SQL ──────────────────────────────────────────────────
        (inst_dir / 'ai_sql.sql').write_text(ver_sql)

        # ── Logs ────────────────────────────────────────────────────
        logs_dir = inst_dir / 'logs'
        logs_dir.mkdir(exist_ok=True)

        # Generation conversation
        gen_conv = gen_inst_dir / 'conversation.txt'
        if gen_conv.exists():
            shutil.copy2(gen_conv, logs_dir / 'generation.txt')

        # Verification conversation (from final verified dir)
        ver_conv = ver_inst_dir / 'conversation.txt'
        if ver_conv.exists():
            shutil.copy2(ver_conv, logs_dir / 'verification.txt')

        # ── instance.json ───────────────────────────────────────────
        ai_funcs = find_ai_funcs(ver_sql)
        det_check = ver_metadata.get('determinism_check', {})
        issues = det_check.get('issues_found', [])
        accepted_variance = any('variance' in i.lower() or 'accept' in i.lower() for i in issues)

        instance_json = {
            "instance_id": iid,
            "variant": variant,
            "db_id": orig['db_id'],

            # Original Spider2 data
            "original": {
                "instruction": orig['instruction'],
                "num_gold_sqls": len(gold_sqls),
                "gold_sql_files": [f"gold_{chr(ord('a') + i)}.sql" for i in range(len(gold_sqls))],
                "execution_results": orig.get('execution_results', []),
                "eval_config": {
                    "ignore_order": orig.get('ignore_order', False),
                    "condition_cols": orig.get('condition_cols', [])
                },
                "external_knowledge": orig.get('external_knowledge', '')
            },

            # AI-enhanced version
            "ai": {
                "instruction": ver_metadata.get('final_instruction', ''),
                "ai_functions": ai_funcs,
                "eval_config": ver_metadata.get('eval_config', {}),
                "accepted_variance": accepted_variance
            },

            # Pipeline metadata
            "generation": {
                "status": ver_metadata.get('final_status', ''),
                "num_rounds": (json.loads((gen_inst_dir / 'metadata.json').read_text())
                               .get('num_rounds', 0) if (gen_inst_dir / 'metadata.json').exists() else 0)
            },
            "verification": _build_verification_info(iid, det_check, all_verified_dirs)
        }

        with open(inst_dir / 'instance.json', 'w') as f:
            json.dump(instance_json, f, indent=2, ensure_ascii=False)

        # ── Track stats ─────────────────────────────────────────────
        stats['included'] += 1
        for func in ai_funcs:
            stats[f'func_{func}'] += 1
        if accepted_variance:
            stats['accepted_variance'] += 1

        index_entries.append({
            "instance_id": iid,
            "dir_name": dir_name,
            "db_id": orig['db_id'],
            "ai_functions": ai_funcs,
            "accepted_variance": accepted_variance,
            "num_gold_sqls": len(gold_sqls)
        })

    # ── Write index.json ────────────────────────────────────────────────
    index_path = output_dir / 'index.json'

    if append and index_path.exists():
        # Merge into existing index
        with open(index_path) as f:
            existing_index = json.load(f)
        existing_instances = existing_index.get('instances', [])
        existing_dir_names = {e['dir_name'] for e in existing_instances}

        new_entries = [e for e in index_entries if e['dir_name'] not in existing_dir_names]
        merged_instances = existing_instances + new_entries

        # Recompute combined stats
        combined_func_usage = Counter()
        combined_variance = 0
        for inst in merged_instances:
            for func in inst.get('ai_functions', []):
                combined_func_usage[func] += 1
            if inst.get('accepted_variance', False):
                combined_variance += 1

        existing_stats = existing_index.get('stats', {})
        index = {
            "description": "Spider2-AISQL Benchmark Dataset",
            "variants": sorted(set([existing_index.get('variant', 'main'), variant])),
            "total_instances": len(merged_instances),
            "stats": {
                "main_included": existing_stats.get('included', len(existing_instances)),
                f"{variant}_included": stats['included'],
                f"{variant}_dropped_not_pass": dropped_not_pass,
                f"{variant}_dropped_ai_removed": dropped_ai,
                f"{variant}_dropped_dedup": len(dedup_dropped),
                "accepted_variance": combined_variance,
                "ai_function_usage": {
                    func: combined_func_usage.get(func, 0) for func in AI_FUNCS
                }
            },
            "instances": merged_instances
        }
        print(f"\n  Appending to existing index ({len(existing_instances)} existing + {len(new_entries)} new)")
    else:
        index = {
            "description": "Spider2-AISQL Benchmark Dataset",
            "variant": variant,
            "total_instances": len(index_entries),
            "stats": {
                "included": stats['included'],
                "dropped_not_pass": dropped_not_pass,
                "dropped_ai_removed": dropped_ai,
                "dropped_dedup": len(dedup_dropped),
                "accepted_variance": stats.get('accepted_variance', 0),
                "ai_function_usage": {
                    func: stats.get(f'func_{func}', 0) for func in AI_FUNCS
                }
            },
            "instances": index_entries
        }

    with open(index_path, 'w') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"✅ Dataset built: {output_dir}")
    print(f"   New instances added: {stats['included']}")
    if append and index_path.exists():
        print(f"   Total in dataset: {index['total_instances']}")
    print(f"   Accepted variance: {stats.get('accepted_variance', 0)}")
    print(f"   AI function usage (this variant):")
    for func in AI_FUNCS:
        count = stats.get(f'func_{func}', 0)
        if count > 0:
            print(f"     {func}: {count}")
    total_dropped = dropped_not_pass + dropped_ai + len(dedup_dropped)
    print(f"   Dropped: {total_dropped} "
          f"({dropped_not_pass} not pass + {dropped_ai} AI removed"
          f"{f' + {len(dedup_dropped)} dedup' if dedup_dropped else ''})")


if __name__ == "__main__":
    main()
