"""
SQL executor for Snowflake.
Handles connection management and query execution with result capture.
"""
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Structured result from SQL execution."""
    status: str  # 'success' or 'error'
    data: Optional[List[Dict[str, Any]]] = None
    num_rows: int = 0
    num_columns: int = 0
    execution_time: Optional[float] = None
    error: Optional[str] = None
    
    def to_dict(self, include_sample: bool = True, sample_size: int = 3) -> Dict[str, Any]:
        """
        Convert to dictionary format.
        
        Args:
            include_sample: Whether to include sample data
            sample_size: Number of sample rows to include
            
        Returns:
            Dictionary representation
        """
        result = {
            'status': self.status,
            'num_rows': self.num_rows,
            'num_columns': self.num_columns,
            'execution_time': self.execution_time,
            'error': self.error
        }
        
        if include_sample and self.data:
            result['sample_data'] = self.data[:sample_size]
        
        return result


class SnowflakeExecutor:
    """Executes SQL queries on Snowflake and captures results."""
    
    def __init__(
        self,
        account: Optional[str] = None,
        user: Optional[str] = None,
        role: Optional[str] = None,
        warehouse: Optional[str] = None,
        token: Optional[str] = None,
        database: Optional[str] = None
    ):
        """
        Initialize Snowflake executor.
        
        Args:
            account: Snowflake account (defaults to env SNOWFLAKE_ACCOUNT)
            user: Snowflake user (defaults to env SNOWFLAKE_USER)
            role: Snowflake role (defaults to env SNOWFLAKE_ROLE)
            warehouse: Snowflake warehouse (defaults to env SNOWFLAKE_WAREHOUSE)
            token: OAuth token (defaults to env SNOWFLAKE_TOKEN)
            database: Default database to use (optional)
        """
        # Import snowflake connector
        try:
            import snowflake.connector
            from snowflake.connector import DictCursor
            self.snowflake = snowflake.connector
            self.DictCursor = DictCursor
        except ImportError:
            raise ImportError(
                "snowflake-connector-python is required. "
                "Install it with: pip install snowflake-connector-python"
            )
        
        # Get configuration from parameters or environment
        self.account = account or os.getenv('SNOWFLAKE_ACCOUNT')
        self.user = user or os.getenv('SNOWFLAKE_USER')
        self.role = role or os.getenv('SNOWFLAKE_ROLE')
        self.warehouse = warehouse or os.getenv('SNOWFLAKE_WAREHOUSE')
        self.token = token or os.getenv('SNOWFLAKE_TOKEN')
        self.database = database  # Current database context
        
        if not self.token:
            raise ValueError(
                "Snowflake token must be provided via parameter or "
                "SNOWFLAKE_TOKEN environment variable"
            )
        
        self.connection = None
    
    def connect(self, database: Optional[str] = None):
        """
        Establish connection to Snowflake.
        
        Args:
            database: Database to connect to (overrides default)
        """
        if self.connection is None:
            db = database or self.database
            connect_params = {
                'account': self.account,
                'user': self.user,
                'password': self.token,
                'warehouse': self.warehouse,
                'role': self.role
            }
            if db:
                connect_params['database'] = db
            self.connection = self.snowflake.connect(**connect_params)
            if db:
                self.database = db
    
    def set_database(self, database: str) -> ExecutionResult:
        """
        Switch to a different database context.
        
        Args:
            database: Database name to switch to
            
        Returns:
            ExecutionResult of the USE DATABASE command
        """
        result = self.execute(f"USE DATABASE {database}")
        if result.status == 'success':
            self.database = database
        return result
    
    def reconnect(self, database: Optional[str] = None):
        """
        Close current connection and create a new one.
        Useful for ensuring clean environment isolation.
        
        Args:
            database: Database to connect to (optional)
        """
        self.disconnect()
        self.connect(database=database)
    
    def disconnect(self):
        """Close Snowflake connection."""
        if self.connection is not None:
            self.connection.close()
            self.connection = None
    
    def execute(
        self, 
        sql_query: str, 
        timeout: int = 120,
        database: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute SQL query and return structured result.
        
        Args:
            sql_query: SQL query to execute
            timeout: Query timeout in seconds
            database: Database to use (will reconnect if different from current)
            
        Returns:
            ExecutionResult with query results or error
        """
        # Ensure connection exists
        if self.connection is None:
            self.connect(database=database)
        # Switch database if needed (USE DATABASE is much faster than reconnect)
        elif database and database != self.database:
            self.set_database(database)
        
        cursor = self.connection.cursor(self.DictCursor)
        
        try:
            start_time = datetime.now()
            cursor.execute(sql_query, timeout=timeout)
            rows = cursor.fetchall()
            end_time = datetime.now()
            
            return ExecutionResult(
                status='success',
                data=rows,
                num_rows=len(rows),
                num_columns=len(rows[0]) if rows else 0,
                execution_time=(end_time - start_time).total_seconds()
            )
            
        except Exception as e:
            return ExecutionResult(
                status='error',
                error=str(e)
            )
        
        finally:
            cursor.close()
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def execute_sql_simple(sql_query: str) -> ExecutionResult:
    """
    Simple function to execute SQL with automatic connection management.
    
    Args:
        sql_query: SQL query to execute
        
    Returns:
        ExecutionResult
        
    Example:
        result = execute_sql_simple("SELECT COUNT(*) FROM my_table")
        if result.status == 'success':
            print(f"Query returned {result.num_rows} rows")
    """
    with SnowflakeExecutor() as executor:
        return executor.execute(sql_query)


if __name__ == "__main__":
    # Test SQL executor
    print("❄️  Snowflake SQL Executor Test")
    print("=" * 60)
    
    try:
        executor = SnowflakeExecutor()
        print(f"✅ Initialized executor")
        print(f"   Account: {executor.account}")
        print(f"   User: {executor.user}")
        print(f"   Role: {executor.role}")
        
        # Test simple query
        print("\nTesting connection with simple query...")
        with executor:
            result = executor.execute("SELECT CURRENT_USER(), CURRENT_ROLE()")
            
            if result.status == 'success':
                print(f"✅ Query successful!")
                print(f"   Rows: {result.num_rows}")
                print(f"   Columns: {result.num_columns}")
                print(f"   Time: {result.execution_time:.2f}s")
                if result.data:
                    print(f"   Result: {result.data[0]}")
            else:
                print(f"❌ Query failed: {result.error}")
    
    except ValueError as e:
        print(f"⚠️  Configuration error: {e}")
        print("   Make sure SNOWFLAKE_TOKEN is set in environment")
    except Exception as e:
        print(f"❌ Error: {e}")

