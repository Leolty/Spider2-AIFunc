#!/usr/bin/env python
"""
Batch Agent Run Script

Runs the iterative SQL generation agent on test cases from the dataset.

Usage:
    python scripts/run_batch.py --input-file my_source_sql.jsonl --output-dir outputs/my_test
    python scripts/run_batch.py --mode multi --input-file my_source_sql.jsonl
    python scripts/run_batch.py --mode multi --input-file my_source_sql.jsonl \\
        --gold-tables-file my_gold_tables.jsonl
"""
import sys
import argparse
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tqdm import tqdm
from dotenv import load_dotenv

from src.core import paths, database
from src.agents import SQLGenerationAgent
from src.agents.multi_sql_agent import MultiSQLAgent
from src.utils import file_io


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run SQL generation agent on batch test cases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "-i", "--input-file",
        type=str,
        default=None,
        help="Input JSONL file path. Required for public use; the internal default is not shipped."
    )
    parser.add_argument(
        "--gold-tables-file",
        type=str,
        default=None,
        help=(
            "Optional JSONL mapping from instance_id to gold_tables. "
            "If omitted and the internal mapping is unavailable, all schemas are loaded without gold-table prioritization."
        )
    )
    parser.add_argument(
        "-n", "--num-entries",
        type=int,
        default=10,
        help="Number of entries to process (default: 10, use -1 for all)"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=15,
        help="Maximum rounds per entry (default: 15)"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="LLM temperature (default: 0.7)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: outputs/batch_YYYYMMDD_HHMMSS)"
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start index in dataset (default: 0)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=True,
        help="Verbose output (default: True)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode (no verbose output)"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume mode, re-process all entries (default: resume is ON)"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=['single', 'multi'],
        default='single',
        help="Agent mode: 'single' uses first gold SQL, 'multi' sees all gold SQLs and resolves ambiguity (default: single)"
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        nargs='+',
        default=None,
        help="Specific instance ID(s) to process (overrides --start-index and -n)"
    )
    parser.add_argument(
        "--diversity",
        action="store_true",
        help="Enable diversity enrichment mode: encourage underrepresented AI functions (AI_SENTIMENT, AI_EXTRACT, AI_AGG)"
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Load environment variables
    load_dotenv(PROJECT_ROOT / '.env')
    
    # Configuration
    num_entries = args.num_entries
    max_rounds = args.max_rounds
    start_index = args.start_index
    verbose = not args.quiet
    resume = not args.no_resume
    temperature = args.temperature
    mode = args.mode
    diversity = args.diversity
    
    # Output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
        if not output_dir.is_absolute():
            output_dir = PROJECT_ROOT / output_dir
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = paths.PROJECT_ROOT / "outputs" / f"batch_{timestamp}"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("🚀 Batch Agent Run")
    print("=" * 60)
    print(f"📊 Configuration:")
    print(f"   Mode: {mode}")
    if diversity:
        print(f"   Diversity: ENABLED (target: AI_SENTIMENT > AI_EXTRACT > AI_AGG)")
    if args.instance_id:
        print(f"   Instance IDs: {args.instance_id}")
    else:
        print(f"   Entries to process: {num_entries}")
        print(f"   Start index: {start_index}")
    print(f"   Max rounds per entry: {max_rounds}")
    print(f"   Temperature: {temperature}")
    print(f"   Verbose: {verbose}")
    print(f"   Resume mode: {resume}")
    print(f"   Output directory: {output_dir}")
    
    # Determine input file
    if args.input_file:
        data_file = Path(args.input_file)
        if not data_file.is_absolute():
            data_file = PROJECT_ROOT / data_file
    else:
        data_file = paths.get_spider2_data_file()
    print(f"   Input file: {data_file}")
    print()

    if not data_file.exists():
        print(f"Error: input file not found: {data_file}")
        print("For public use, pass --input-file with your own source JSONL.")
        print("See docs/generation.md for the required format.")
        return 1
    
    # Load data
    print("📂 Loading data...")
    all_entries = file_io.read_jsonl(data_file)
    required_fields = {"instance_id", "db_id", "instruction", "gold_sqls"}
    for line_num, entry in enumerate(all_entries, 1):
        missing = required_fields - set(entry)
        if missing:
            print(f"Error: {data_file}:{line_num} is missing required fields: {sorted(missing)}")
            return 1
        if not entry.get("gold_sqls"):
            print(f"Error: {data_file}:{line_num} has no gold_sqls for {entry.get('instance_id')}")
            return 1
    
    # Filter by instance IDs if specified
    if args.instance_id:
        instance_ids = set(args.instance_id)
        entries = [e for e in all_entries if e['instance_id'] in instance_ids]
        if len(entries) != len(instance_ids):
            found_ids = {e['instance_id'] for e in entries}
            missing_ids = instance_ids - found_ids
            print(f"⚠️  Warning: Instance IDs not found: {missing_ids}")
        print(f"✅ Loaded {len(entries)} entries by instance ID (total available: {len(all_entries)})")
    else:
        if num_entries == -1:
            entries = all_entries[start_index:]
        else:
            entries = all_entries[start_index:start_index + num_entries]
        print(f"✅ Loaded {len(entries)} entries (from index {start_index}, total available: {len(all_entries)})")
    
    # Update num_entries to actual count for display
    num_entries = len(entries)
    
    # Show entries
    print(f"\n📝 Entry IDs:")
    for i, entry in enumerate(entries, 1):
        print(f"   {i:2d}. {entry['instance_id']:15s} | DB: {entry['db_id']:20s} | {entry['instruction'][:60]}...")
    print()
    
    # Initialize LLM client
    print("🤖 Initializing LLM client...")
    from src.core import LLMFactory
    llm_client = LLMFactory.create_from_env()
    print(f"✅ LLM: {llm_client.provider} ({llm_client.model_name})")
    
    # Initialize agent based on mode
    if mode == 'multi':
        agent = MultiSQLAgent(llm_client, max_rounds=max_rounds, verbose=verbose, temperature=temperature)
        print(f"✅ MultiSQLAgent initialized with max_rounds={max_rounds}, temperature={temperature}")
    else:
        agent = SQLGenerationAgent(llm_client, max_rounds=max_rounds, verbose=verbose, temperature=temperature)
        print(f"✅ SQLGenerationAgent initialized with max_rounds={max_rounds}, temperature={temperature}")
    
    # Initialize database mapper
    db_mapper = database.DatabaseMapper(paths.DATABASES_DIR)
    print(f"✅ Database mapper loaded {len(db_mapper)} databases")
    
    # Load gold tables mapping (for smart schema formatting)
    if args.gold_tables_file:
        gold_tables_path = Path(args.gold_tables_file)
        if not gold_tables_path.is_absolute():
            gold_tables_path = PROJECT_ROOT / gold_tables_path
        if not gold_tables_path.exists():
            print(f"Error: --gold-tables-file not found: {gold_tables_path}")
            return 1
    else:
        gold_tables_path = paths.get_gold_tables_file()

    if gold_tables_path.exists():
        gold_tables_data = file_io.read_jsonl(gold_tables_path)
        gold_tables_map = {
            item['instance_id']: item.get('gold_tables', [])
            for item in gold_tables_data
            if 'instance_id' in item
        }
        print(f"✅ Gold tables loaded: {len(gold_tables_map)} entries")
    else:
        gold_tables_map = {}
        print("⚠️  Gold tables mapping not found; schema formatting will not prioritize source tables.")
        print("   This is okay for public own-data runs, but providing --gold-tables-file improves prompts.")
    print()
    
    # Run batch processing
    results = []
    stats = {
        'done': 0,
        'max_rounds_reached': 0,
        'parse_error': 0,
        'error': 0,
        'skipped': 0,
        'rejected': 0
    }
    
    print("🚀 Starting batch processing...\n")
    
    for i, entry in enumerate(tqdm(entries, desc="Processing"), 1):
        instance_id = entry['instance_id']
        instance_dir = output_dir / instance_id
        final_sql_path = instance_dir / 'final.sql'
        
        # Check if already completed (resume mode)
        if resume and final_sql_path.exists():
            tqdm.write(f"[{i}/{num_entries}] ⏭️  Skipping {instance_id} (already has final.sql)")
            stats['skipped'] += 1
            continue
        
        # If directory exists but no final.sql, delete it (incomplete previous run)
        if resume and instance_dir.exists() and not final_sql_path.exists():
            tqdm.write(f"[{i}/{num_entries}] 🗑️  Removing incomplete {instance_id} (no final.sql)")
            shutil.rmtree(instance_dir)
        
        # Get first gold SQL version
        gold_sql = entry['gold_sqls'][0] if entry.get('gold_sqls') else None
        
        result = {
            'instance_id': instance_id,
            'db_id': entry['db_id'],
            'original_instruction': entry['instruction'],
            'original_sql': gold_sql
        }
        
        try:
            tqdm.write(f"\n{'='*60}")
            tqdm.write(f"[{i}/{num_entries}] Processing: {instance_id}")
            tqdm.write(f"{'='*60}")
            
            # Load database schema (smart format with gold tables prioritized)
            tqdm.write(f"  📊 Loading schema for DB: {entry['db_id']}...")
            db_path = db_mapper.get_path(entry['db_id'])
            if db_path is None:
                raise FileNotFoundError(
                    f"Database resources not found for {entry['db_id']} under {paths.DATABASES_DIR}. "
                    "Run python scripts/setup_resources.py and link/copy the Spider2-Snow resources."
                )
            tables = database.SchemaLoader.get_all_tables(db_path)
            gold_table_names = gold_tables_map.get(instance_id, [])
            schema_content = database.SchemaFormatter.format_database_schema_smart(
                db_id=entry['db_id'],
                all_tables=tables,
                gold_table_names=gold_table_names,
                token_budget=64000
            )
            tqdm.write(f"  ✅ Schema loaded ({len(tables)} tables, {len(gold_table_names)} gold)")
            
            # Load external knowledge content (if provided as filename)
            external_knowledge_content = None
            ext_knowledge_field = entry.get('external_knowledge')
            if ext_knowledge_field:
                # It's a filename, load the actual content
                ext_knowledge_content = database.load_external_knowledge(
                    paths.KNOWLEDGE_DIR, ext_knowledge_field
                )
                if ext_knowledge_content:
                    tqdm.write(f"  📚 External knowledge loaded: {ext_knowledge_field}")
                else:
                    tqdm.write(f"  ⚠️ External knowledge file not found: {ext_knowledge_field}")
            
            # Run agent based on mode
            tqdm.write(f"  🤖 Starting agent (max {max_rounds} rounds, mode={mode})...")
            
            if mode == 'multi':
                # Multi mode: pass all gold SQLs and execution results
                gold_sqls = entry.get('gold_sqls', [])
                execution_results = entry.get('execution_results', [])
                tqdm.write(f"  Multi mode: {len(gold_sqls)} gold SQLs provided")
                
                agent_result = agent.generate(
                    instruction=entry['instruction'],
                    gold_sqls=gold_sqls,
                    execution_results=execution_results,
                    schema_content=schema_content,
                    db_id=entry['db_id'],
                    external_knowledge=external_knowledge_content,
                    diversity_hint=diversity
                )
            else:
                # Single mode: use first gold SQL and its result
                exec_result = {}
                for er in entry.get('execution_results', []):
                    if er.get('status') == 'success':
                        exec_result = er
                        break
                
                agent_result = agent.generate(
                    instruction=entry['instruction'],
                    sql_query=gold_sql,
                    result=exec_result,
                    schema_content=schema_content,
                    db_id=entry['db_id'],
                    external_knowledge=external_knowledge_content,
                    diversity_hint=diversity
                )
            
            tqdm.write(f"  ✅ Agent finished: {agent_result['final_status']} ({len(agent_result['rounds'])} rounds)")
            
            # Merge agent result
            result.update(agent_result)
            
            # Update stats
            status = agent_result['final_status']
            if status == 'done':
                stats['done'] += 1
            elif status == 'rejected':
                stats['rejected'] += 1
            elif status == 'max_rounds_reached':
                stats['max_rounds_reached'] += 1
            elif 'parse_error' in status:
                stats['parse_error'] += 1
            else:
                stats['error'] += 1
                
        except Exception as e:
            tqdm.write(f"  💥 Exception: {str(e)}...")
            result['final_status'] = 'error'
            result['error'] = str(e)
            result['rounds'] = []
            stats['error'] += 1
        
        results.append(result)
        
        # Save to structured directory
        tqdm.write(f"  💾 Saving to directory: {output_dir / entry['instance_id']}")
        file_io.save_agent_result_to_dir(
            result=result,
            output_dir=output_dir,
            messages=agent.messages,
            gold_result=entry.get('result')
        )
        
        # Also save JSONL summary
        file_io.write_jsonl(results, output_dir / "results_all.jsonl")
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 BATCH PROCESSING COMPLETE")
    print("=" * 60)
    processed = num_entries - stats['skipped']
    print(f"\nStatistics:")
    print(f"   Skipped (resumed):  {stats['skipped']:3d} / {num_entries}")
    print(f"   Done:               {stats['done']:3d} / {processed} processed")
    if stats['rejected'] > 0:
        print(f"   Rejected:           {stats['rejected']:3d} / {processed} processed")
    print(f"   Max rounds reached: {stats['max_rounds_reached']:3d} / {processed} processed")
    print(f"   Parse errors:       {stats['parse_error']:3d} / {processed} processed")
    print(f"   Other errors:       {stats['error']:3d} / {processed} processed")
    
    success_rate = stats['done'] / processed * 100 if processed > 0 else 0
    print(f"\n   Success rate (of processed): {success_rate:.1f}%")
    print(f"\n   Results saved to: {output_dir}")
    
    return 0 if stats['error'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
