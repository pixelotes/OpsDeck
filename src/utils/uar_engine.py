import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional
from ..extensions import db

logger = logging.getLogger(__name__)

class AccessReviewEngine:
    """
    Engine for comparing datasets using an in-memory SQLite database.
    """
    
    def __init__(self):
        # Create an in-memory SQLite database
        self.conn = sqlite3.connect(':memory:', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def load_dataset(self, table_name: str, data: List[Dict[str, Any]]):
        """
        Loads a list of dictionaries into a table.
        Infer schema from the first record (naive approach).
        """
        if not data:
            logger.warning(f"No data to load for table {table_name}")
            return

        # Sanitize table name
        safe_table_name = "".join(x for x in table_name if x.isalnum() or x == "_")
        
        # 1. Infer Columns
        # We'll take the first item as a template. 
        # For a more robust solution, we might scan all items or use a schema definition.
        first_record = data[0]
        columns = list(first_record.keys())
        
        # 2. Create Table
        # Everything is treated as TEXT or INTEGER/REAL; finer typing is not needed here.
        # relying on SQLite's dynamic typing.
        cols_def = ", ".join([f'"{c}" TEXT' for c in columns])
        create_stmt = f'CREATE TABLE IF NOT EXISTS "{safe_table_name}" ({cols_def})'
        self.conn.execute(create_stmt)
        
        # 3. Insert Data
        placeholders = ", ".join(["?"] * len(columns))
        insert_sql = f'INSERT INTO "{safe_table_name}" ({", ".join(f"{c}" for c in columns)}) VALUES ({placeholders})'
        
        rows_to_insert = []
        for item in data:
            # Ensure we respect the column order and handle missing keys
            row = []
            for col in columns:
                val = item.get(col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)  # Store objects as JSON strings
                elif val is not None:
                    val = str(val)
                row.append(val)
            rows_to_insert.append(row)
            
        self.conn.executemany(insert_sql, rows_to_insert)
        self.conn.commit()
        logger.info(f"Loaded {len(rows_to_insert)} rows into table '{safe_table_name}'")

    def load_from_report(self, table_name: str, report_id: int):
        """
        Loads data from an OpsDeck Enterprise Report into the in-memory DB.

        Returns the rows it loaded, so a caller can record how many there were. Every
        other source in UARAutomationService._load_dataset returns its rows and the
        execution's snapshot counts them; this one used to return nothing, which would
        have recorded a row count of zero for a dataset that had in fact been loaded.
        """
        try:
            from opsdeck_enterprise.models.report import Report
            report = db.session.get(Report, report_id)
            if not report:
                raise ValueError(f"Report with ID {report_id} not found.")
            
            data = json.loads(report.data)
            
            # Reports stored as {"items": [...], ...} or direct list
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and 'items' in data:
                items = data['items']
            
            self.load_dataset(table_name, items)
            return items

        except ImportError:
            logger.error("OpsDeck Enterprise plugin not found or Report model unimportable.")
            raise

    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Executes a raw SQL query on the in-memory database.
        RESTRICTED: Only SELECT and PRAGMA statements allowed for safety.
        """
        query_upper = query.strip().upper()
        if not (query_upper.startswith("SELECT") or query_upper.startswith("PRAGMA")):
            raise ValueError("Only SELECT and PRAGMA queries are allowed.")

        try:
            cursor = self.conn.execute(query)
            results = [dict(row) for row in cursor.fetchall()]
            return results
        except sqlite3.Error as e:
            logger.error(f"SQL Error: {e}")
            raise

    def cleanup(self):
        """Close the connection."""
        self.conn.close()


    def load_from_subscription(self, table_name: str, subscription_id: int):
        """
        Loads user access data from a specific Subscription.
        """
        from ..models import Subscription
        sub = db.session.get(Subscription, subscription_id)
        if not sub:
            raise ValueError(f"Subscription {subscription_id} not found")
        
        # Get users from subscription (direct + licensed)
        # We need a standardized format for the rows
        rows = []
        
        # 1. Direct assignments (if any, depends on model)
        if hasattr(sub, 'users'):
            for u in sub.users:
                rows.append({
                    'user_id': u.id,
                    'email': u.email,
                    'name': u.name,
                    'source': 'Subscription Assignment',
                    'subscription_name': sub.name
                })
                
        # 2. Licenses assigned to users linked to this subscription
        if hasattr(sub, 'licenses'):
            for lic in sub.licenses:
                if lic.user_id:
                     # Fetch user eagerly or lazily
                    from ..models import User
                    u = db.session.get(User, lic.user_id)
                    if u:
                        rows.append({
                            'user_id': u.id,
                            'email': u.email,
                            'name': u.name, 
                            'source': 'License Seat',
                            'subscription_name': sub.name,
                            'license_key': lic.license_key
                        })
        
        self.load_dataset(table_name, rows)

    def load_from_service(self, table_name: str, service_id: int):
        """
        Loads user access data from a Business Service (using get_effective_users).
        """
        from ..models import BusinessService
        svc = db.session.get(BusinessService, service_id)
        if not svc:
            raise ValueError(f"Service {service_id} not found")
            
        effective_users = svc.get_effective_users()
        rows = []
        for item in effective_users:
            u = item['user']
            rows.append({
                'user_id': u.id,
                'email': u.email,
                'name': u.name,
                'source': item['source'],
                'service_name': svc.name,
                'details': str(item['ref']) if item['ref'] else 'Direct'
            })
            
        self.load_dataset(table_name, rows)

    def perform_structured_comparison(
        self, 
        key_field_a: str, 
        key_field_b: str, 
        field_mappings: Optional[List[Dict[str, str]]] = None,
        # Legacy support
        key_field: Optional[str] = None,
        compare_fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Performs a symmetric difference comparison between dataset_a and dataset_b.
        Supports comparing columns with different names across datasets.
        
        Args:
            key_field_a: The unique identifier column in Dataset A (e.g., 'github_user').
            key_field_b: The unique identifier column in Dataset B (e.g., 'login').
            field_mappings: List of {"field_a": "...", "field_b": "..."} for attribute comparison.
            key_field: (Legacy) Single key field name, used if key_field_a/b not provided.
            compare_fields: (Legacy) List of fields to compare (assumes same name in both datasets).
            
        Returns:
            List of findings.
        """
        # Legacy compatibility: if old-style params provided, convert
        if key_field and not key_field_a:
            key_field_a = key_field
            key_field_b = key_field
        if compare_fields and not field_mappings:
            field_mappings = [{"field_a": f, "field_b": f} for f in compare_fields]
        
        field_mappings = field_mappings or []
        
        # Fetch all data as dicts, keyed by the respective key columns
        try:
            data_a = {str(row[key_field_a]): dict(row) for row in self.execute_query("SELECT * FROM dataset_a")}
        except Exception:
            data_a = {}
            
        try:
            data_b = {str(row[key_field_b]): dict(row) for row in self.execute_query("SELECT * FROM dataset_b")}
        except Exception:
            data_b = {}
            
        findings = []
        
        all_keys = set(data_a.keys()) | set(data_b.keys())
        
        for key in all_keys:
            in_a = key in data_a
            in_b = key in data_b
            
            row_a = data_a.get(key, {})
            row_b = data_b.get(key, {})
            
            # Base finding object with clear labeling
            finding = {
                'key': key,
                'key_field_a': key_field_a,
                'key_field_b': key_field_b,
                'status': 'Match'
            }
            
            # Include data from both sides with prefixes to avoid collision
            for k, v in row_a.items():
                finding[f'a_{k}'] = v
            for k, v in row_b.items():
                finding[f'b_{k}'] = v
            
            if in_a and not in_b:
                finding['finding_type'] = 'Left Only (A)'
                finding['status'] = f'Present in A ({key_field_a}={key}) but missing in B'
                findings.append(finding)
                
            elif in_b and not in_a:
                finding['finding_type'] = 'Right Only (B)'
                finding['status'] = f'Present in B ({key_field_b}={key}) but missing in A'
                findings.append(finding)
                
            else:
                # In both - check for attribute mismatches using field mappings
                mismatches = []
                for mapping in field_mappings:
                    field_a = mapping.get('field_a', '')
                    field_b = mapping.get('field_b', '')
                    
                    val_a = str(row_a.get(field_a, ''))
                    val_b = str(row_b.get(field_b, ''))
                    
                    if val_a != val_b:
                        mismatches.append(f"A.{field_a}='{val_a}' ≠ B.{field_b}='{val_b}'")
                
                if mismatches:
                    finding['finding_type'] = 'Mismatch'
                    finding['status'] = "; ".join(mismatches)
                    findings.append(finding)
        
        return findings

