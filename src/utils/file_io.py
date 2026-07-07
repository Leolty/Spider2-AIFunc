"""
File I/O utilities for reading and writing JSONL files.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles date, datetime, time, Decimal, etc."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, time):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


def read_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    """
    Read a JSONL file and return list of dictionaries.
    
    Args:
        file_path: Path to JSONL file
        
    Returns:
        List of parsed JSON objects
    """
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def read_jsonl_iter(file_path: Path) -> Iterator[Dict[str, Any]]:
    """
    Read a JSONL file lazily (line by line).
    
    Args:
        file_path: Path to JSONL file
        
    Yields:
        Parsed JSON objects one at a time
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(data: List[Dict[str, Any]], file_path: Path):
    """
    Write list of dictionaries to JSONL file.
    
    Args:
        data: List of dictionaries to write
        file_path: Path to output JSONL file
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False, cls=CustomJSONEncoder) + '\n')


def append_jsonl(item: Dict[str, Any], file_path: Path):
    """
    Append a single item to JSONL file.
    
    Args:
        item: Dictionary to append
        file_path: Path to JSONL file
    """
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(item, ensure_ascii=False, cls=CustomJSONEncoder) + '\n')


def read_text(file_path: Path) -> str:
    """
    Read text file content.
    
    Args:
        file_path: Path to text file
        
    Returns:
        File content as string
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def write_text(content: str, file_path: Path):
    """
    Write content to text file.
    
    Args:
        content: Text content to write
        file_path: Path to output file
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def save_agent_result_to_dir(
    result: Dict[str, Any],
    output_dir: Path,
    messages: List[Dict[str, str]] = None,
    gold_result: Dict[str, Any] = None
):
    """
    Save agent result to a structured directory with human-readable files.
    
    Args:
        result: Agent result dict containing:
            - instance_id
            - db_id
            - original_instruction
            - original_sql
            - rounds (list of round data)
            - final_status
            - final_sql (optional)
            - final_instruction (optional)
        output_dir: Base output directory
        messages: Optional conversation messages (with system prompt)
        gold_result: Optional gold SQL execution result for comparison
    """
    # Create directory for this instance
    instance_dir = output_dir / result['instance_id']
    instance_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Save metadata.json
    metadata = {
        'instance_id': result['instance_id'],
        'db_id': result['db_id'],
        'final_status': result['final_status'],
        'num_rounds': len(result.get('rounds', [])),
        'has_final_sql': 'final_sql' in result,
        'original_instruction': result.get('original_instruction', ''),
        'final_instruction': result.get('final_instruction', ''),
        'eval_config': result.get('final_eval_config')
    }
    with open(instance_dir / 'metadata.json', 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, cls=CustomJSONEncoder)
    
    # 2. Save conversation.txt (complete dialogue with system prompt)
    conversation_lines = []
    conversation_lines.append("=" * 80)
    conversation_lines.append("COMPLETE CONVERSATION HISTORY")
    conversation_lines.append("=" * 80)
    conversation_lines.append("")
    
    if messages:
        for i, msg in enumerate(messages):
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
    
    conversation_text = "\n".join(conversation_lines)
    write_text(conversation_text, instance_dir / 'conversation.txt')
    
    # 3. Save instructions.txt (original vs final)
    instructions_lines = []
    instructions_lines.append("=" * 80)
    instructions_lines.append("INSTRUCTIONS COMPARISON")
    instructions_lines.append("=" * 80)
    instructions_lines.append("")
    
    instructions_lines.append("=" * 80)
    instructions_lines.append("ORIGINAL INSTRUCTION")
    instructions_lines.append("=" * 80)
    instructions_lines.append("")
    instructions_lines.append(result.get('original_instruction', 'N/A'))
    instructions_lines.append("")
    instructions_lines.append("")
    
    instructions_lines.append("=" * 80)
    instructions_lines.append("FINAL INSTRUCTION (AI-Enhanced)")
    instructions_lines.append("=" * 80)
    instructions_lines.append("")
    instructions_lines.append(result.get('final_instruction', 'N/A'))
    instructions_lines.append("")
    
    instructions_text = "\n".join(instructions_lines)
    write_text(instructions_text, instance_dir / 'instructions.txt')
    
    # 4. Save SQL files
    if result.get('original_sql'):
        write_text(result['original_sql'], instance_dir / 'original.sql')
    
    if result.get('final_sql'):
        write_text(result['final_sql'], instance_dir / 'final.sql')
    
    # 5. Save rounds detail (structured JSON)
    if result.get('rounds'):
        rounds_detail = {
            'num_rounds': len(result['rounds']),
            'final_status': result['final_status'],
            'rounds': result['rounds']
        }
        with open(instance_dir / 'rounds_detail.json', 'w', encoding='utf-8') as f:
            json.dump(rounds_detail, f, indent=2, ensure_ascii=False, cls=CustomJSONEncoder)
    
    # 6. Save each round's SQL separately
    sql_dir = instance_dir / 'rounds_sql'
    sql_dir.mkdir(exist_ok=True)
    for i, round_data in enumerate(result.get('rounds', []), 1):
        if round_data.get('sql'):
            write_text(round_data['sql'], sql_dir / f'round_{i}.sql')
    
    # 7. Save execution_results.txt - record each round's execution result
    exec_lines = []
    exec_lines.append("=" * 80)
    exec_lines.append("EXECUTION RESULTS BY ROUND")
    exec_lines.append("=" * 80)
    exec_lines.append("")
    exec_lines.append(f"Instance: {result['instance_id']}")
    exec_lines.append(f"Final Status: {result['final_status']}")
    exec_lines.append(f"Total Rounds: {len(result.get('rounds', []))}")
    exec_lines.append("")
    
    for i, round_data in enumerate(result.get('rounds', []), 1):
        exec_lines.append("=" * 80)
        exec_lines.append(f"ROUND {i}")
        exec_lines.append("=" * 80)
        exec_lines.append("")
        
        action = round_data.get('action', 'unknown')
        exec_lines.append(f"Action: {action}")
        exec_lines.append("")
        
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
                exec_lines.append("")
                if exec_result.get('data'):
                    exec_lines.append("   Sample Data (all rows):")
                    exec_lines.append("-" * 40)
                    data = exec_result['data']
                    # Support both CSV string format and List[Dict] format
                    if isinstance(data, str):
                        # CSV string - display directly (truncate if very long)
                        lines = data.strip().split('\n')
                        for line in lines[:50]:  # Show at most 50 rows
                            exec_lines.append(f"   {line}")
                        if len(lines) > 50:
                            exec_lines.append(f"   ... ({len(lines) - 50} more rows)")
                    else:
                        for row in data:
                            exec_lines.append(f"   {json.dumps(row, ensure_ascii=False, cls=CustomJSONEncoder)}")
                    exec_lines.append("-" * 40)
            else:
                exec_lines.append(f"❌ EXECUTION FAILED")
                exec_lines.append(f"   Status: {status}")
                exec_lines.append(f"   Error: {exec_result.get('error', 'Unknown error')}")
        else:
            if action == 'done':
                exec_lines.append("   [No execution - agent marked done]")
            else:
                exec_lines.append("   [No execution result recorded]")
        exec_lines.append("")
    
    # Summary
    exec_lines.append("=" * 80)
    exec_lines.append("SUMMARY")
    exec_lines.append("=" * 80)
    exec_lines.append("")
    success_count = sum(1 for r in result.get('rounds', []) 
                        if r.get('execution', {}).get('status') == 'success')
    failed_count = sum(1 for r in result.get('rounds', []) 
                       if r.get('execution', {}).get('status') in ['failed', 'error'])
    exec_lines.append(f"Successful executions: {success_count}")
    exec_lines.append(f"Failed executions: {failed_count}")
    exec_lines.append(f"Final status: {result['final_status']}")
    exec_lines.append("")
    
    write_text("\n".join(exec_lines), instance_dir / 'execution_results.txt')
    
    # 8. Save results_comparison.txt - compare gold SQL result vs AI SQL result
    if gold_result is not None:
        comp_lines = []
        comp_lines.append("=" * 80)
        comp_lines.append("RESULTS COMPARISON: Gold SQL vs AI SQL")
        comp_lines.append("=" * 80)
        comp_lines.append("")
        
        # Gold SQL Result
        comp_lines.append("=" * 80)
        comp_lines.append("GOLD SQL EXECUTION RESULT (Original)")
        comp_lines.append("=" * 80)
        comp_lines.append("")
        
        if isinstance(gold_result, dict):
            # Check if it's a successful result:
            # - Either has 'status': 'success'
            # - Or has 'num_rows' and 'data' fields (original data format)
            gold_status = gold_result.get('status')
            has_data = 'num_rows' in gold_result and 'data' in gold_result
            
            if gold_status == 'success' or has_data:
                comp_lines.append(f"✅ Status: SUCCESS")
                comp_lines.append(f"   Rows: {gold_result.get('num_rows', 'N/A')}")
                comp_lines.append(f"   Columns: {gold_result.get('num_columns', 'N/A')}")
                exec_time = gold_result.get('execution_time')
                if exec_time is not None:
                    comp_lines.append(f"   Execution Time: {exec_time:.2f}s")
                comp_lines.append("")
                if gold_result.get('data'):
                    comp_lines.append("   Data (all rows):")
                    comp_lines.append("-" * 40)
                    data = gold_result['data']
                    if isinstance(data, list):
                        for row in data:
                            comp_lines.append(f"   {json.dumps(row, ensure_ascii=False, cls=CustomJSONEncoder)}")
                    else:
                        comp_lines.append(f"   {json.dumps(data, ensure_ascii=False, cls=CustomJSONEncoder)}")
                    comp_lines.append("-" * 40)
            else:
                comp_lines.append(f"❌ Status: {gold_status or 'FAILED'}")
                comp_lines.append(f"   Error: {gold_result.get('error', 'Unknown error')}")
        else:
            comp_lines.append(f"   Raw result: {gold_result}")
        comp_lines.append("")
        
        # AI SQL Result (from final successful round)
        comp_lines.append("=" * 80)
        comp_lines.append("AI SQL EXECUTION RESULT (Final)")
        comp_lines.append("=" * 80)
        comp_lines.append("")
        
        # Find the last successful execution
        ai_result = None
        for round_data in reversed(result.get('rounds', [])):
            exec_data = round_data.get('execution')
            if exec_data and exec_data.get('status') == 'success':
                ai_result = exec_data
                break
        
        if ai_result:
            comp_lines.append(f"✅ Status: SUCCESS")
            comp_lines.append(f"   Rows: {ai_result.get('num_rows', 'N/A')}")
            comp_lines.append(f"   Columns: {ai_result.get('num_columns', 'N/A')}")
            exec_time = ai_result.get('execution_time')
            if exec_time is not None:
                comp_lines.append(f"   Execution Time: {exec_time:.2f}s")
            comp_lines.append("")
            if ai_result.get('data'):
                comp_lines.append("   Data (all rows):")
                comp_lines.append("-" * 40)
                for row in ai_result['data']:
                    comp_lines.append(f"   {json.dumps(row, ensure_ascii=False, cls=CustomJSONEncoder)}")
                comp_lines.append("-" * 40)
        else:
            comp_lines.append("❌ No successful AI SQL execution found")
            # Show last error if available
            for round_data in reversed(result.get('rounds', [])):
                exec_data = round_data.get('execution')
                if exec_data:
                    comp_lines.append(f"   Last execution status: {exec_data.get('status')}")
                    if exec_data.get('error'):
                        comp_lines.append(f"   Error: {exec_data.get('error')}")
                    break
        comp_lines.append("")
        
        write_text("\n".join(comp_lines), instance_dir / 'results_comparison.txt')


if __name__ == "__main__":
    # Test file I/O
    import tempfile
    
    print("🧪 Testing File I/O Utilities")
    print("=" * 60)
    
    # Test JSONL
    test_data = [
        {'id': 1, 'name': 'Alice'},
        {'id': 2, 'name': 'Bob'},
        {'id': 3, 'name': 'Charlie'}
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.jsonl"
        
        # Write
        write_jsonl(test_data, test_file)
        print(f"✅ Wrote {len(test_data)} items to JSONL")
        
        # Read
        loaded_data = read_jsonl(test_file)
        print(f"✅ Read {len(loaded_data)} items from JSONL")
        
        # Verify
        assert loaded_data == test_data
        print("✅ Data matches!")
        
        # Test iterator
        count = sum(1 for _ in read_jsonl_iter(test_file))
        print(f"✅ Iterator read {count} items")
    
    print("\n🎉 All tests passed!")



