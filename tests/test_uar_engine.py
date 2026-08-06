import json
from src.utils.uar_engine import AccessReviewEngine

def test_engine_initialization():
    engine = AccessReviewEngine()
    assert engine.conn is not None
    engine.cleanup()

def test_load_dataset_and_query():
    engine = AccessReviewEngine()
    
    data = [
        {"id": 1, "name": "Alice", "role": "Admin"},
        {"id": 2, "name": "Bob", "role": "User"}
    ]
    
    engine.load_dataset("users", data)
    
    results = engine.execute_query("SELECT * FROM users ORDER BY id")
    assert len(results) == 2
    assert results[0]['name'] == 'Alice'
    assert results[1]['role'] == 'User'
    
    engine.cleanup()

def test_load_dataset_with_nested_json():
    engine = AccessReviewEngine()
    
    data = [
        {"id": 1, "config": {"enabled": True, "limits": [1, 2]}}
    ]
    
    engine.load_dataset("settings", data)
    
    results = engine.execute_query("SELECT * FROM settings")
    config_str = results[0]['config']
    config = json.loads(config_str)
    
    assert config['enabled'] is True
    assert config['limits'] == [1, 2]
    
    engine.cleanup()

def test_join_query_between_tables():
    engine = AccessReviewEngine()
    
    users = [{"email": "alice@example.com", "status": "active"}]
    github = [{"login": "alice", "email": "alice@example.com"}]
    
    engine.load_dataset("dataset_a", users)
    engine.load_dataset("dataset_b", github)
    
    query = """
    SELECT a.status, b.login 
    FROM dataset_a a 
    JOIN dataset_b b ON a.email = b.email
    """
    
    results = engine.execute_query(query)
    assert len(results) == 1
    assert results[0]['status'] == 'active'
    assert results[0]['login'] == 'alice'
    
    engine.cleanup()

def test_custom_property_prefixing():
    # Verify that we can load data with custom prefixes if needed, 
    # though this is mostly logic in the Route, the Engine just processes what it gets.
    engine = AccessReviewEngine()
    data = [{"id": 1, "custom_field_github_user": "alice"}]
    engine.load_dataset("users", data)
    
    results = engine.execute_query("SELECT custom_field_github_user FROM users")
    assert results[0]['custom_field_github_user'] == 'alice'
    engine.cleanup()

def test_structured_comparison():
    engine = AccessReviewEngine()
    
    # Dataset A (Reference)
    data_a = [
        {"email": "alice@co.com", "role": "admin"},
        {"email": "bob@co.com", "role": "user"}
    ]
    
    # Dataset B (Target)
    data_b = [
        {"email": "alice@co.com", "role": "admin"}, # Match
        {"email": "bob@co.com", "role": "admin"},  # Mismatch (Role)
        {"email": "charlie@co.com", "role": "user"} # Right Only
    ]
    
    engine.load_dataset("dataset_a", data_a)
    engine.load_dataset("dataset_b", data_b)
    
    # Test
    findings = engine.perform_structured_comparison(
        key_field_a="email",
        key_field_b="email",
        field_mappings=[{"field_a": "role", "field_b": "role"}]
    )
    
    # Findings should contain:
    # 1. Bob (Mismatch)
    # 2. Charlie (Right Only)
    # Alice is a match, so usually not returned? 
    # Ah, the logic appends pure matches to 'findings' too? 
    # Let's check logic: 
    #   if in_a and not in_b: Left Only
    #   elif in_b and not in_a: Right Only
    #   else: check mismatches. If mismatches, add.
    # The current implementation DOES NOT add pure matches to 'findings' list.
    
    # Convert to dict for easier assertions
    find_map = {f['key']: f for f in findings}
    
    assert 'bob@co.com' in find_map
    assert find_map['bob@co.com']['finding_type'] == 'Mismatch'
    assert 'role' in find_map['bob@co.com']['status'] # "role: admin != user" or similar
    
    assert 'charlie@co.com' in find_map
    assert find_map['charlie@co.com']['finding_type'] == 'Right Only (B)'
    
    assert 'alice@co.com' not in find_map
    
    engine.cleanup()
