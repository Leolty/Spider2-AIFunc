"""
Database schema operations.
Handles loading, mapping, and formatting database schemas and sample data.
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class DatabaseMapper:
    """Manages database ID to directory path mapping."""
    
    def __init__(self, databases_path: Path):
        """
        Initialize database mapper.
        
        Args:
            databases_path: Path to the databases directory
        """
        self.databases_path = Path(databases_path)
        self._mapping = self._build_mapping()
    
    def _build_mapping(self) -> Dict[str, Path]:
        """Scan databases directory and build db_id to path mapping."""
        mapping = {}
        
        if not self.databases_path.exists():
            return mapping
        
        for db_dir in self.databases_path.iterdir():
            if db_dir.is_dir():
                mapping[db_dir.name] = db_dir
        
        return mapping
    
    def get_path(self, db_id: str) -> Optional[Path]:
        """
        Get directory path for a database ID.
        
        Args:
            db_id: Database identifier
            
        Returns:
            Path to database directory, or None if not found
        """
        return self._mapping.get(db_id)
    
    def exists(self, db_id: str) -> bool:
        """Check if a database ID exists in the mapping."""
        return db_id in self._mapping
    
    def __len__(self) -> int:
        """Return number of databases in mapping."""
        return len(self._mapping)
    
    def list_databases(self) -> List[str]:
        """Return list of all database IDs."""
        return list(self._mapping.keys())


class SchemaLoader:
    """Loads database schemas and sample data."""
    
    @staticmethod
    def load_table_schema(table_json_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load schema info for a single table.
        
        Args:
            table_json_path: Path to table JSON file
            
        Returns:
            Table schema dictionary, or None if loading fails
        """
        try:
            with open(table_json_path, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    
    @staticmethod
    def get_all_tables(db_path: Path) -> List[Dict[str, Any]]:
        """
        Get all table schemas for a database.
        
        Args:
            db_path: Path to database directory
            
        Returns:
            List of table schema dictionaries
        """
        all_tables = []
        
        for schema_dir in db_path.iterdir():
            if schema_dir.is_dir():
                for table_file in schema_dir.glob("*.json"):
                    table_info = SchemaLoader.load_table_schema(table_file)
                    if table_info:
                        all_tables.append(table_info)
        
        return all_tables


class SchemaFormatter:
    """Formats database schemas as human-readable text."""
    
    @staticmethod
    def format_sample_rows(
        table_info: Dict[str, Any], 
        max_rows: int = 3, 
        max_cols: int = 8
    ) -> str:
        """
        Format sample rows as markdown table.
        
        Args:
            table_info: Table information dictionary
            max_rows: Maximum number of rows to display
            max_cols: Maximum number of columns to display
            
        Returns:
            Markdown-formatted table string
        """
        if 'sample_rows' not in table_info or not table_info['sample_rows']:
            return "No sample data available"
        
        sample_rows = table_info['sample_rows'][:max_rows]
        column_names = table_info.get('column_names', [])
        
        if not column_names:
            return json.dumps(sample_rows, indent=2)
        
        display_columns = column_names[:max_cols]
        
        # Build table
        header = "| " + " | ".join(display_columns) + " |"
        separator = "|" + "|".join(["---" for _ in display_columns]) + "|"
        
        rows = []
        for row in sample_rows:
            values = []
            for col in display_columns:
                val = row.get(col, "NULL")
                if isinstance(val, (dict, list)):
                    val_str = str(val)[:40] + "..." if len(str(val)) > 40 else str(val)
                else:
                    val_str = str(val)[:40] if val is not None else "NULL"
                values.append(val_str)
            rows.append("| " + " | ".join(values) + " |")
        
        return "\n".join([header, separator] + rows)
    
    @staticmethod
    def format_table_schema(
        table_info: Dict[str, Any],
        max_cols: Optional[int] = None,
        max_desc_len: int = 100
    ) -> str:
        """
        Format table schema info as markdown.
        
        Args:
            table_info: Table information dictionary
            max_cols: Maximum columns to display (None = all)
            max_desc_len: Maximum description length per column
            
        Returns:
            Markdown-formatted schema description
        """
        if not table_info:
            return ""
        
        table_name = table_info.get('table_fullname', table_info.get('table_name', 'Unknown'))
        column_names = table_info.get('column_names', [])
        column_types = table_info.get('column_types', [])
        descriptions = table_info.get('description', [])
        
        total_cols = len(column_names)
        display_cols = column_names[:max_cols] if max_cols else column_names
        
        # Build columns list
        columns_list = []
        for i, col_name in enumerate(display_cols):
            col_type = column_types[i] if i < len(column_types) else "UNKNOWN"
            desc = descriptions[i] if i < len(descriptions) else ""
            # Truncate description if too long
            if desc and len(desc) > max_desc_len:
                desc = desc[:max_desc_len] + "..."
            desc_str = f" - {desc}" if desc else ""
            columns_list.append(f"  - `{col_name}` ({col_type}){desc_str}")
        
        # Add truncation notice if needed
        if max_cols and total_cols > max_cols:
            columns_list.append(f"  ... ({total_cols - max_cols} more columns)")
        
        columns_text = "\n".join(columns_list) if columns_list else "No columns info"
        sample_data_text = SchemaFormatter.format_sample_rows(table_info)
        
        return f"""**Table: `{table_name}`**

Columns:
{columns_text}

Sample data:
{sample_data_text}
"""
    
    @staticmethod
    def format_table_brief(table_info: Dict[str, Any], max_cols: int = 5) -> str:
        """
        Format table as a brief one-liner (table name + first few columns with types).
        
        Args:
            table_info: Table information dictionary
            max_cols: Maximum columns to show
            
        Returns:
            Brief one-line table description
        """
        if not table_info:
            return ""
        
        table_name = table_info.get('table_fullname', table_info.get('table_name', 'Unknown'))
        column_names = table_info.get('column_names', [])
        column_types = table_info.get('column_types', [])
        
        total_cols = len(column_names)
        cols_preview = []
        for i in range(min(max_cols, total_cols)):
            col_type = column_types[i] if i < len(column_types) else "?"
            cols_preview.append(f"{column_names[i]}({col_type})")
        
        cols_str = ", ".join(cols_preview)
        if total_cols > max_cols:
            cols_str += f" ...+{total_cols - max_cols} more"
        
        return f"{table_name}: {cols_str}"
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count (roughly 4 chars per token for English)."""
        return len(text) // 4
    
    @staticmethod
    def format_database_schema(
        db_id: str,
        tables: List[Dict[str, Any]]
    ) -> str:
        """
        Format complete database schema with all tables.
        
        Args:
            db_id: Database identifier
            tables: List of table information dictionaries
            
        Returns:
            Complete formatted database schema
        """
        if not tables:
            return f"Database: {db_id}\n\n⚠️ No schema information found for this database"
        
        tables_text = "\n---\n\n".join(
            SchemaFormatter.format_table_schema(t) for t in tables
        )
        
        return f"""Database: {db_id}

This database contains {len(tables)} tables. Below are the complete schemas with sample data from each table.

---

{tables_text}---
"""
    
    @staticmethod
    def format_database_schema_smart(
        db_id: str,
        all_tables: List[Dict[str, Any]],
        gold_table_names: List[str],
        token_budget: int = 64000
    ) -> str:
        """
        Format database schema with smart token budget allocation.
        
        Strategy:
        1. Layer 1: All table names (compact list) - always included
        2. Layer 2: Gold tables with full schema - add one by one until budget reached
        3. Layer 3: Other tables with brief schema - add one by one with remaining budget
        
        Args:
            db_id: Database identifier
            all_tables: List of all table information dictionaries
            gold_table_names: List of gold table full names (e.g., "SCHEMA.TABLE")
            token_budget: Total token budget (default: 64000)
            
        Returns:
            Formatted database schema within budget
        """
        if not all_tables:
            return f"Database: {db_id}\n\n⚠️ No schema information found for this database"
        
        # Separate gold tables and other tables
        gold_tables = []
        other_tables = []
        for t in all_tables:
            full_name = t.get('table_fullname', '')
            if full_name in gold_table_names:
                gold_tables.append(t)
            else:
                other_tables.append(t)
        
        # Header (always include)
        header = f"""## Database: {db_id}

Total tables: {len(all_tables)} | Gold tables: {len(gold_tables)} | Other tables: {len(other_tables)}

"""
        header_tokens = SchemaFormatter.estimate_tokens(header)
        
        # Layer 1: All table names (always include)
        all_names = [t.get('table_fullname', t.get('table_name', '')) for t in all_tables]
        layer1_text = "### All Tables in Database\n" + ", ".join(all_names)
        layer1_tokens = SchemaFormatter.estimate_tokens(layer1_text)
        
        # Calculate remaining budget for layers 2 and 3
        remaining_budget = token_budget - header_tokens - layer1_tokens
        
        # Reserve 80% of remaining budget for gold tables, 20% for other tables
        gold_budget = int(remaining_budget * 0.8)
        other_budget = remaining_budget - gold_budget
        
        # Layer 2: Gold tables - add one by one until budget reached
        gold_schemas = []
        gold_tokens_used = 0
        gold_tables_added = 0
        
        # Decide max columns per table based on number of gold tables
        if len(gold_tables) > 50:
            max_cols_per_table = 15
        elif len(gold_tables) > 20:
            max_cols_per_table = 25
        else:
            max_cols_per_table = None  # No limit
        
        for t in gold_tables:
            schema_text = SchemaFormatter.format_table_schema(t, max_cols=max_cols_per_table)
            schema_tokens = SchemaFormatter.estimate_tokens(schema_text)
            
            # Check if adding this table would exceed budget
            if gold_tokens_used + schema_tokens > gold_budget:
                break  # Stop adding gold tables
            
            gold_schemas.append(schema_text)
            gold_tokens_used += schema_tokens
            gold_tables_added += 1
        
        # Build layer 2 text
        if gold_schemas:
            if gold_tables_added < len(gold_tables):
                truncated_count = len(gold_tables) - gold_tables_added
                layer2_header = f"### Gold Tables (Detailed Schema) - showing {gold_tables_added} of {len(gold_tables)} ({truncated_count} tables truncated due to token limit)\n\n"
            else:
                layer2_header = "### Gold Tables (Detailed Schema)\n\n"
            layer2_text = layer2_header + "\n---\n\n".join(gold_schemas)
        else:
            layer2_text = ""
        
        # Add unused gold budget to other budget
        other_budget += (gold_budget - gold_tokens_used)
        
        # Layer 3: Other tables - add one by one until budget reached
        other_briefs = []
        other_tokens_used = 0
        other_tables_added = 0
        max_brief_cols = 5  # Brief format
        
        if other_tables and other_budget > 500:
            for t in other_tables:
                brief = SchemaFormatter.format_table_brief(t, max_cols=max_brief_cols)
                brief_tokens = SchemaFormatter.estimate_tokens(brief)
                
                # Check if adding this table would exceed budget
                if other_tokens_used + brief_tokens > other_budget:
                    break  # Stop adding other tables
                
                other_briefs.append(brief)
                other_tokens_used += brief_tokens
                other_tables_added += 1
        
        # Build layer 3 text
        if other_briefs:
            if other_tables_added < len(other_tables):
                truncated_count = len(other_tables) - other_tables_added
                layer3_text = f"### Other Tables (Summary) - showing {other_tables_added} of {len(other_tables)} ({truncated_count} tables truncated due to token limit)\n\n" + "\n".join(other_briefs)
            else:
                layer3_text = "### Other Tables (Summary)\n\n" + "\n".join(other_briefs)
        else:
            layer3_text = ""
        
        # Combine all layers
        result = header + layer1_text + "\n\n" + layer2_text
        if layer3_text:
            result += "\n\n" + layer3_text
        
        return result


def load_external_knowledge(knowledge_path: Path, doc_name: str) -> str:
    """
    Load external knowledge document.
    
    Args:
        knowledge_path: Path to knowledge directory
        doc_name: Document filename
        
    Returns:
        Document content as string, or empty string if loading fails
    """
    doc_path = knowledge_path / doc_name
    
    if not doc_path.exists():
        return ""
    
    try:
        with open(doc_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""


if __name__ == "__main__":
    # Test database operations
    from .paths import DATABASES_DIR
    
    print("🗄️  Database Schema Operations Test")
    print("=" * 60)
    
    # Test mapper
    mapper = DatabaseMapper(DATABASES_DIR)
    print(f"Found {len(mapper)} databases")
    
    # List first 5 databases
    dbs = mapper.list_databases()[:5]
    print(f"\nFirst 5 databases: {', '.join(dbs)}")
    
    # Test loading a database
    if dbs:
        test_db = dbs[0]
        db_path = mapper.get_path(test_db)
        print(f"\nLoading schema for '{test_db}'...")
        
        tables = SchemaLoader.get_all_tables(db_path)
        print(f"  Found {len(tables)} tables")
        
        if tables:
            print(f"\n  First table preview:")
            formatted = SchemaFormatter.format_table_schema(tables[0])
            # Print first 300 characters
            print("  " + formatted[:300].replace("\n", "\n  ") + "...")
    
    print("\n✅ Database operations test complete!")

