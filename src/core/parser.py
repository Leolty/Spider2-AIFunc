"""
LLM response parser.
Extracts structured information from LLM responses.
"""
import re
import json
from typing import Dict, Optional, Any


class LLMResponseParser:
    """Parses LLM responses to extract structured content."""
    
    @staticmethod
    def parse_agent_response(response_text: str) -> Dict[str, Any]:
        """
        Parse agent LLM response to extract action, thinking, instruction, SQL, and eval_config.
        
        Args:
            response_text: Raw agent LLM response text
            
        Returns:
            Dictionary with keys:
            - 'action': 'continue', 'done', or None
            - 'thinking': Extracted reasoning or None
            - 'instruction': Extracted instruction or None
            - 'sql': Extracted SQL query or None
            - 'eval_config': Extracted eval config dict or None (only for 'done' action)
            - 'parse_status': 'success', 'missing_action', 'missing_sql', etc.
        """
        result = {
            'action': None,
            'thinking': None,
            'instruction': None,
            'sql': None,
            'eval_config': None,
            'parse_status': 'success'
        }
        
        # Extract thinking
        thinking_match = re.search(r'<thinking>(.*?)</thinking>', response_text, re.DOTALL)
        if thinking_match:
            result['thinking'] = thinking_match.group(1).strip()
        
        # Extract action
        action_match = re.search(r'<action>(.*?)</action>', response_text, re.DOTALL)
        if action_match:
            action = action_match.group(1).strip().lower()
            if action in ['continue', 'done', 'reject']:
                result['action'] = action
            else:
                result['parse_status'] = f'invalid_action:{action}'
        else:
            result['parse_status'] = 'missing_action'
        
        # Extract instruction
        instruction_match = re.search(
            r'<instruction>(.*?)</instruction>', 
            response_text, 
            re.DOTALL
        )
        if instruction_match:
            result['instruction'] = instruction_match.group(1).strip()
        
        # Extract SQL (between ```sql and ```)
        sql_match = re.search(
            r'<sql>\s*```sql\s*(.*?)\s*```\s*</sql>', 
            response_text, 
            re.DOTALL
        )
        if sql_match:
            result['sql'] = sql_match.group(1).strip()
        else:
            if result['parse_status'] == 'success':
                # Check if SQL was truncated (incomplete tags)
                has_sql_open = '<sql>' in response_text
                has_sql_close = '</sql>' in response_text
                has_sql_code_start = '```sql' in response_text
                backtick_count = response_text.count('```')
                
                if has_sql_open and not has_sql_close:
                    # <sql> opened but never closed - truncated
                    result['parse_status'] = 'truncated_sql'
                elif has_sql_code_start and backtick_count % 2 != 0:
                    # Odd number of ``` means unclosed code block - truncated
                    result['parse_status'] = 'truncated_sql'
                else:
                    result['parse_status'] = 'missing_sql'
        
        # Extract eval_config (between ```json and ```, inside <eval_config> tags)
        # Only expected when action is 'done', but we parse it anyway
        eval_config_match = re.search(
            r'<eval_config>\s*```json\s*(.*?)\s*```\s*</eval_config>', 
            response_text, 
            re.DOTALL
        )
        if eval_config_match:
            try:
                result['eval_config'] = json.loads(eval_config_match.group(1).strip())
            except json.JSONDecodeError:
                # If JSON parsing fails, store the raw text
                result['eval_config'] = {'raw': eval_config_match.group(1).strip(), 'parse_error': True}
        
        return result
    
    @staticmethod
    def parse(response_text: str) -> Dict[str, Optional[str]]:
        """
        Parse LLM response to extract instruction, SQL, and thinking.
        
        Args:
            response_text: Raw LLM response text
            
        Returns:
            Dictionary with keys:
            - 'instruction': Extracted instruction or None
            - 'sql': Extracted SQL query or None
            - 'thinking': Extracted reasoning or None
            - 'parse_status': 'success', 'missing_instruction', 'missing_sql', or 'missing_both'
        """
        result = {
            'instruction': None,
            'sql': None,
            'thinking': None,
            'parse_status': 'success'
        }
        
        # Extract thinking
        thinking_match = re.search(r'<thinking>(.*?)</thinking>', response_text, re.DOTALL)
        if thinking_match:
            result['thinking'] = thinking_match.group(1).strip()
        
        # Extract instruction
        instruction_match = re.search(
            r'<instruction>(.*?)</instruction>', 
            response_text, 
            re.DOTALL
        )
        if instruction_match:
            result['instruction'] = instruction_match.group(1).strip()
        else:
            result['parse_status'] = 'missing_instruction'
        
        # Extract SQL (between ```sql and ```)
        sql_match = re.search(
            r'<sql>\s*```sql\s*(.*?)\s*```\s*</sql>', 
            response_text, 
            re.DOTALL
        )
        if sql_match:
            result['sql'] = sql_match.group(1).strip()
        else:
            # Update status if SQL is also missing
            if result['parse_status'] == 'missing_instruction':
                result['parse_status'] = 'missing_both'
            else:
                result['parse_status'] = 'missing_sql'
        
        return result
    
    @staticmethod
    def extract_thinking(response_text: str) -> Optional[str]:
        """
        Extract only the thinking section from response.
        
        Args:
            response_text: Raw LLM response text
            
        Returns:
            Thinking content or None
        """
        match = re.search(r'<thinking>(.*?)</thinking>', response_text, re.DOTALL)
        return match.group(1).strip() if match else None
    
    @staticmethod
    def extract_instruction(response_text: str) -> Optional[str]:
        """
        Extract only the instruction from response.
        
        Args:
            response_text: Raw LLM response text
            
        Returns:
            Instruction or None
        """
        match = re.search(
            r'<instruction>(.*?)</instruction>', 
            response_text, 
            re.DOTALL
        )
        return match.group(1).strip() if match else None
    
    @staticmethod
    def extract_sql(response_text: str) -> Optional[str]:
        """
        Extract only the SQL from response.
        
        Args:
            response_text: Raw LLM response text
            
        Returns:
            SQL query or None
        """
        match = re.search(
            r'<sql>\s*```sql\s*(.*?)\s*```\s*</sql>', 
            response_text, 
            re.DOTALL
        )
        return match.group(1).strip() if match else None
    
    @staticmethod
    def is_valid_response(response_text: str) -> bool:
        """
        Check if response contains all required sections.
        
        Args:
            response_text: Raw LLM response text
            
        Returns:
            True if response has both instruction and sql
        """
        parsed = LLMResponseParser.parse(response_text)
        return parsed['parse_status'] == 'success'


if __name__ == "__main__":
    # Test parser with sample response
    sample_response = """
<thinking>
The original query counts patents. I can add sentiment analysis to analyze patent descriptions.
</thinking>

<instruction>
Count patents and classify their descriptions into technical categories: ['electronics', 'software', 'mechanical', 'chemical'].
</instruction>

<sql>
```sql
SELECT 
    COUNT(*) as total_patents,
    AI_CLASSIFY(description, ['electronics', 'software', 'mechanical', 'chemical']) as category
FROM patents
GROUP BY category
```
</sql>
"""
    
    print("🔍 LLM Response Parser Test")
    print("=" * 60)
    
    parsed = LLMResponseParser.parse(sample_response)
    
    print(f"Parse Status: {parsed['parse_status']}")
    print(f"\nThinking: {parsed['thinking'][:100]}..." if parsed['thinking'] else "None")
    print(f"\nInstruction: {parsed['instruction'][:100]}..." if parsed['instruction'] else "None")
    print(f"\nSQL: {parsed['sql'][:100]}..." if parsed['sql'] else "None")
    
    print(f"\n✅ Valid response: {LLMResponseParser.is_valid_response(sample_response)}")

