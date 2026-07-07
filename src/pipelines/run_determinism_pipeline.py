"""
Pipeline for running determinism checks on generated AI SQL.

This pipeline:
1. Reads outputs from a previous SQL generation run
2. Runs determinism checks on each instance (empirical + specification)
3. Writes results to a NEW directory (does not modify original)

Usage:
    python -m src.pipelines.run_determinism_pipeline \\
        --input-dir outputs/run \\
        --output-dir outputs/run_verified \\
        --num-executions 3

    # Limit to specific instances
    python -m src.pipelines.run_determinism_pipeline \\
        --input-dir outputs/run \\
        --output-dir outputs/run_verified \\
        --instances sf_bq033 sf_bq091
"""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from tqdm import tqdm

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.utils import file_io

if TYPE_CHECKING:
    from src.agents.determinism_agent import CheckResult


def load_instance(instance_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Load an instance from its directory.
    
    Expected structure:
        instance_dir/
        ├── final.sql
        ├── metadata.json (contains eval_config, final_instruction)
        └── ...
    
    Returns:
        Dict with sql, instruction, eval_config, metadata
    """
    # Required: final.sql
    sql_file = instance_dir / 'final.sql'
    if not sql_file.exists():
        return None
    
    sql = sql_file.read_text().strip()
    
    # Required: metadata.json
    metadata_file = instance_dir / 'metadata.json'
    if not metadata_file.exists():
        return None
    
    with open(metadata_file) as f:
        metadata = json.load(f)
    
    # Get instruction from metadata
    instruction = metadata.get('final_instruction', '')
    if not instruction:
        instruction = metadata.get('original_instruction', '')
    
    # Get eval_config
    eval_config = metadata.get('eval_config', {
        'ignore_order': True,
        'condition_cols': []
    })
    
    return {
        'instance_id': instance_dir.name,
        'sql': sql,
        'instruction': instruction,
        'eval_config': eval_config,
        'metadata': metadata
    }


def save_result(
    result: CheckResult,
    original_metadata: Dict[str, Any],
    output_dir: Path,
    instance_id: str,
    original_sql: str,
    original_instruction: str
):
    """Save check result to output directory with detailed logs."""
    instance_output = output_dir / instance_id
    instance_output.mkdir(parents=True, exist_ok=True)
    
    # 1. Save final SQL
    (instance_output / 'final.sql').write_text(result.final_sql)
    
    # 2. Save original SQL for comparison
    (instance_output / 'original.sql').write_text(original_sql)
    
    # 3. Save instructions comparison
    instructions_content = f"""{'=' * 80}
INSTRUCTIONS COMPARISON
{'=' * 80}

{'=' * 80}
ORIGINAL INSTRUCTION
{'=' * 80}

{original_instruction}

{'=' * 80}
FINAL INSTRUCTION (After Determinism Check)
{'=' * 80}

{result.final_instruction}

{'=' * 80}
CHANGES
{'=' * 80}

{"No changes made." if original_instruction == result.final_instruction else "Instruction was modified for determinism."}
"""
    (instance_output / 'instructions.txt').write_text(instructions_content)
    
    # 4. Save conversation.txt - complete dialogue
    conversation_lines = []
    conversation_lines.append("=" * 80)
    conversation_lines.append("DETERMINISM CHECK CONVERSATION")
    conversation_lines.append("=" * 80)
    conversation_lines.append("")
    conversation_lines.append(f"Instance: {instance_id}")
    conversation_lines.append(f"Initial: {'CONSISTENT' if result.empirical_result and result.empirical_result.is_consistent else 'INCONSISTENT'}")
    conversation_lines.append(f"Status: {result.status}")
    conversation_lines.append(f"Rounds: {len(result.rounds)}")
    conversation_lines.append("")
    
    for i, msg in enumerate(result.messages):
        role = msg['role'].upper()
        content = msg['content']
        
        conversation_lines.append("=" * 80)
        if role == "SYSTEM":
            conversation_lines.append("SYSTEM PROMPT")
        elif role == "USER":
            conversation_lines.append(f"USER (Message {i})")
        elif role == "ASSISTANT":
            conversation_lines.append(f"ASSISTANT (Message {i})")
        conversation_lines.append("=" * 80)
        conversation_lines.append("")
        conversation_lines.append(content)
        conversation_lines.append("")
    
    (instance_output / 'conversation.txt').write_text("\n".join(conversation_lines))
    
    # 5. Save rounds_detail.json - structured round data
    rounds_detail = {
        'num_rounds': len(result.rounds),
        'status': result.status,
        'is_deterministic': result.is_deterministic,
        'issues_found': result.issues_found,
        'rounds': result.rounds
    }
    with open(instance_output / 'rounds_detail.json', 'w') as f:
        json.dump(rounds_detail, f, indent=2, default=str)
    
    # 6. Save each round's SQL separately
    if result.rounds:
        sql_dir = instance_output / 'rounds_sql'
        sql_dir.mkdir(exist_ok=True)
        for i, round_data in enumerate(result.rounds, 1):
            # Extract SQL from LLM response if available
            llm_response = round_data.get('llm_response', '')
            import re
            sql_match = re.search(r'<sql>\s*```sql\s*(.*?)\s*```\s*</sql>', llm_response, re.DOTALL)
            if sql_match:
                (sql_dir / f'round_{i}.sql').write_text(sql_match.group(1).strip())
    
    # 7. Save execution_results.txt
    exec_lines = []
    exec_lines.append("=" * 80)
    exec_lines.append("EXECUTION RESULTS BY ROUND")
    exec_lines.append("=" * 80)
    exec_lines.append("")
    exec_lines.append(f"Instance: {instance_id}")
    exec_lines.append(f"Final Status: {result.status}")
    exec_lines.append(f"Total Rounds: {len(result.rounds)}")
    exec_lines.append("")
    
    # Empirical check results
    if result.empirical_result:
        exec_lines.append("=" * 80)
        exec_lines.append("EMPIRICAL CONSISTENCY CHECK")
        exec_lines.append("=" * 80)
        exec_lines.append("")
        exec_lines.append(f"Executions: {result.empirical_result.execution_count}")
        exec_lines.append(f"Consistent: {'Yes' if result.empirical_result.is_consistent else 'No'}")
        exec_lines.append("")
    
    # Round by round
    for i, round_data in enumerate(result.rounds, 1):
        exec_lines.append("=" * 80)
        exec_lines.append(f"ROUND {i}")
        exec_lines.append("=" * 80)
        exec_lines.append("")
        
        action = round_data.get('action', 'unknown')
        exec_lines.append(f"Action: {action}")
        
        # Show thinking summary (first 500 chars)
        thinking = round_data.get('thinking', '')
        if thinking:
            exec_lines.append(f"Thinking (summary): {thinking[:500]}...")
        
        exec_result = round_data.get('execution')
        if exec_result:
            status = exec_result.get('status', 'unknown')
            if status == 'success':
                exec_lines.append(f"✅ EXECUTION SUCCESS")
                exec_lines.append(f"   Rows: {exec_result.get('num_rows', 'N/A')}")
                exec_lines.append(f"   Columns: {exec_result.get('num_columns', 'N/A')}")
                exec_time = exec_result.get('execution_time')
                if exec_time is not None:
                    exec_lines.append(f"   Execution Time: {exec_time:.2f}s")
            else:
                exec_lines.append(f"❌ EXECUTION FAILED")
                exec_lines.append(f"   Error: {exec_result.get('error', 'Unknown')}")
        else:
            if action == 'done':
                exec_lines.append("   [No execution - agent marked done]")
        exec_lines.append("")
    
    (instance_output / 'execution_results.txt').write_text("\n".join(exec_lines))
    
    # 8. Update and save metadata.json
    new_metadata = original_metadata.copy()
    new_metadata.update({
        'final_instruction': result.final_instruction,
        'eval_config': result.eval_config,
        'determinism_check': {
            'status': result.status,
            'is_deterministic': result.is_deterministic,
            'num_rounds': len(result.rounds),
            'issues_found': result.issues_found,
            'empirical_consistent': result.empirical_result.is_consistent if result.empirical_result else None,
        }
    })
    
    with open(instance_output / 'metadata.json', 'w') as f:
        json.dump(new_metadata, f, indent=2)
    
    # 9. Save determinism_check.json - detailed check result
    check_details = {
        'status': result.status,
        'is_deterministic': result.is_deterministic,
        'empirical_result': {
            'is_consistent': result.empirical_result.is_consistent,
            'execution_count': result.empirical_result.execution_count,
            'failure_count': result.empirical_result.failure_count
        } if result.empirical_result else None,
        'issues_found': result.issues_found,
        'num_rounds': len(result.rounds),
        'sql_changed': original_sql != result.final_sql,
        'instruction_changed': original_instruction != result.final_instruction,
    }
    
    with open(instance_output / 'determinism_check.json', 'w') as f:
        json.dump(check_details, f, indent=2)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    num_executions: int = 3,
    max_rounds: int = 5,
    instances: Optional[List[str]] = None,
    verbose: bool = True,
    timeout: int = 240,
    max_failures: int = 2,
    skip_passed: bool = False,
    resume: bool = False
):
    """
    Run determinism check pipeline.
    
    Args:
        input_dir: Directory containing generated outputs
        output_dir: Directory to write verified outputs (NEW, not modified in place)
        num_executions: Number of times to execute each SQL for empirical check
        max_rounds: Maximum rounds for verification
        instances: Optional list of specific instance IDs to process
        verbose: Print progress
        timeout: SQL execution timeout in seconds
        max_failures: Max allowed execution failures before aborting N-run check
        skip_passed: If True, skip instances that already have status 'pass' in input_dir
        resume: If True, skip instances that already have determinism_check.json in output_dir
    """
    # Find all instances
    all_instances = []
    for subdir in input_dir.iterdir():
        if subdir.is_dir() and (subdir / 'final.sql').exists():
            if instances is None or subdir.name in instances:
                all_instances.append(subdir)
    
    all_instances.sort(key=lambda x: x.name)
    
    print(f"🔍 Determinism Check Pipeline")
    print(f"=" * 60)
    print(f"📁 Input: {input_dir}")
    print(f"📁 Output: {output_dir}")
    print(f"🔄 Executions per SQL: {num_executions}")
    print(f"🔄 Max rounds: {max_rounds}")
    print(f"⏱️  SQL timeout: {timeout}s")
    print(f"⚠️  Max failures tolerated: {max_failures}")
    print(f"⏭️  Skip passed: {skip_passed}")
    print(f"🔄 Resume: {resume}")
    print(f"📊 Instances to check: {len(all_instances)}")
    print()
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize agent
    from src.core import LLMFactory
    from src.agents.determinism_agent import DeterminismCheckAgent

    llm_client = LLMFactory.create_from_env()
    agent = DeterminismCheckAgent(
        llm_client=llm_client,
        num_executions=num_executions,
        max_rounds=max_rounds,
        verbose=verbose,
        timeout=timeout,
        max_failures=max_failures
    )
    
    print(f"🤖 LLM: {llm_client.provider} ({llm_client.model_name})")
    print()
    
    # Track stats
    stats = {
        'pass': 0,
        'fixed': 0,
        'failed': 0,
        'skipped': 0
    }
    
    results_summary = []
    
    for instance_dir in tqdm(all_instances, desc="Checking"):
        instance_id = instance_dir.name
        
        # Resume: skip instances already completed in the OUTPUT directory
        if resume:
            output_check = output_dir / instance_id / 'determinism_check.json'
            if output_check.exists():
                try:
                    with open(output_check) as f:
                        existing = json.load(f)
                    existing_status = existing.get('status', '')
                    if existing_status:  # any completed status = skip
                        if verbose:
                            tqdm.write(f"⏭️  {instance_id}: Resumed (already {existing_status} in output)")
                        stats['skipped'] += 1
                        if existing_status == 'pass':
                            stats['pass'] = stats.get('pass', 0) + 1
                        elif existing_status == 'fixed':
                            stats['fixed'] = stats.get('fixed', 0) + 1
                        results_summary.append({
                            'instance_id': instance_id,
                            'status': existing_status,
                            'is_deterministic': existing.get('is_deterministic', False),
                            'issues_found': existing.get('issues_found', []),
                            'num_rounds': existing.get('num_rounds', 0),
                            'skipped': True
                        })
                        continue
                except (json.JSONDecodeError, KeyError):
                    pass  # Re-run if existing result is corrupted
        
        # Skip already-passed instances if requested
        if skip_passed:
            # Check input dir's determinism_check.json for pass status
            input_check = instance_dir / 'determinism_check.json'
            if input_check.exists():
                try:
                    with open(input_check) as f:
                        existing = json.load(f)
                    if existing.get('status') == 'pass':
                        # Copy entire instance directory to output
                        import shutil
                        dest = output_dir / instance_id
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(instance_dir, dest)
                        if verbose:
                            tqdm.write(f"⏭️  {instance_id}: Skipped (already passed, copied to output)")
                        stats['skipped'] += 1
                        stats['pass'] = stats.get('pass', 0) + 1
                        results_summary.append({
                            'instance_id': instance_id,
                            'status': 'pass',
                            'is_deterministic': True,
                            'issues_found': [],
                            'num_rounds': existing.get('num_rounds', 0),
                            'skipped': True
                        })
                        continue
                except (json.JSONDecodeError, KeyError):
                    pass  # Re-run if existing result is corrupted
        
        # Load instance
        instance_data = load_instance(instance_dir)
        if not instance_data:
            if verbose:
                tqdm.write(f"⏭️  {instance_id}: Skipped (missing required files)")
            stats['skipped'] += 1
            continue
        
        if verbose:
            tqdm.write(f"\n📋 {instance_id}")
        
        try:
            # Run check
            result = agent.check(
                sql=instance_data['sql'],
                instruction=instance_data['instruction'],
                eval_config=instance_data['eval_config']
            )
            
            # Save result
            save_result(
                result=result,
                original_metadata=instance_data['metadata'],
                output_dir=output_dir,
                instance_id=instance_id,
                original_sql=instance_data['sql'],
                original_instruction=instance_data['instruction']
            )
            
            # Update stats
            stats[result.status] = stats.get(result.status, 0) + 1
            
            # Summary
            status_icons = {
                'pass': '✅',
                'fixed': '🔧',
                'failed': '❌'
            }
            icon = status_icons.get(result.status, '❓')
            
            if verbose:
                tqdm.write(f"  {icon} {result.status} ({len(result.rounds)} rounds)")
                if result.issues_found:
                    for issue in result.issues_found[:2]:
                        tqdm.write(f"     - {issue}")
            
            results_summary.append({
                'instance_id': instance_id,
                'status': result.status,
                'is_deterministic': result.is_deterministic,
                'issues_found': result.issues_found,
                'num_rounds': len(result.rounds)
            })
            
        except Exception as e:
            if verbose:
                tqdm.write(f"  💥 Error: {str(e)[:60]}")
            stats['failed'] += 1
            results_summary.append({
                'instance_id': instance_id,
                'status': 'error',
                'error': str(e)
            })
    
    # Save summary
    summary_file = output_dir / 'check_summary.jsonl'
    file_io.write_jsonl(results_summary, summary_file)
    
    # Print final stats
    print()
    print("=" * 60)
    print("📊 Final Statistics")
    print("=" * 60)
    print(f"✅ Pass (no changes needed): {stats['pass']}")
    print(f"🔧 Fixed (specification updated): {stats['fixed']}")
    print(f"❌ Failed: {stats['failed']}")
    print(f"⏭️  Skipped: {stats['skipped']}")
    print()
    print(f"💾 Results saved to: {output_dir}")
    print(f"📋 Summary: {summary_file}")


def main():
    parser = argparse.ArgumentParser(description='Run determinism checks on generated AI SQL')
    parser.add_argument(
        '--input-dir', '-i',
        type=str,
        required=True,
        help='Input directory containing generated outputs'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        required=True,
        help='Output directory for verified results (will be created)'
    )
    parser.add_argument(
        '--num-executions', '-n',
        type=int,
        default=3,
        help='Number of times to execute each SQL (default: 3)'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=5,
        help='Maximum rounds for verification (default: 5)'
    )
    parser.add_argument(
        '--instances',
        nargs='+',
        help='Specific instance IDs to check (default: all)'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Reduce output verbosity'
    )
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = project_root / input_dir
    
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    
    if not input_dir.exists():
        print(f"❌ Input directory does not exist: {input_dir}")
        sys.exit(1)
    
    run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        num_executions=args.num_executions,
        max_rounds=args.max_rounds,
        instances=args.instances,
        verbose=not args.quiet
    )


if __name__ == '__main__':
    main()
