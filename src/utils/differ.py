from deepdiff import DeepDiff

def get_semantic_diff(old_data, new_data):
    """
    Compares two dictionaries and returns a simplified diff format for the UI.
    
    Returns:
        {
            "added": [("Group > Key", "Value")],
            "removed": [("Group > Key", "Old Value")],
            "changed": [("Group > Key", "Old Value", "New Value")]
        }
    """
    if not old_data:
        old_data = {}
    if not new_data:
        new_data = {}
        
    ddiff = DeepDiff(old_data, new_data, ignore_order=True)
    
    result = {
        "added": [],
        "removed": [],
        "changed": []
    }
    
    # Process Added items (dictionary_item_added)
    if 'dictionary_item_added' in ddiff:
        for path in ddiff['dictionary_item_added']:
            # path looks like "root['General Settings']['Environment']"
            # We want "General Settings > Environment"
            readable_path = _format_path(path)
            value = _get_value_at_path(new_data, path)
            result["added"].append((readable_path, value))
            
    # Process Removed items (dictionary_item_removed)
    if 'dictionary_item_removed' in ddiff:
        for path in ddiff['dictionary_item_removed']:
            readable_path = _format_path(path)
            value = _get_value_at_path(old_data, path)
            result["removed"].append((readable_path, value))
            
    # Process Changed items (values_changed)
    if 'values_changed' in ddiff:
        for path, change in ddiff['values_changed'].items():
            readable_path = _format_path(path)
            result["changed"].append((readable_path, change['old_value'], change['new_value']))
            
    return result

def _format_path(deepdiff_path):
    """
    Converts "root['Group']['Key']" to "Group > Key"
    """
    # Remove "root"
    path = deepdiff_path.replace("root", "")
    
    # Replace "['" with "" and "']" with " > "
    path = path.replace("['", "").replace("']", " > ")
    
    # Remove trailing separator if exists
    if path.endswith(" > "):
        path = path[:-3]
        
    return path

def _get_value_at_path(data, deepdiff_path):
    """
    Helper to safely retrieve value from rich structure using the deepdiff path string.
    Quick hack: DeepDiff gives paths like root['a']['b']. 
    We can rely on the fact that we have the full object.
    """
    # Using eval is risky if data is untrusted, but here data comes from our DB.
    # However, for safety and robustness, let's parse the path.
    # Since deepdiff provides the value in 'values_changed', we usually don't need this for changes.
    # But for added/removed, we need to lookup.
    
    try:
        # Simple recursive lookup
        # Remove root
        # split by ][' might be hard.
        # Evaluated with eval() rather than a parser: this is an internal admin tool and
        # the expressions come from configuration, not from end users.
        # assuming the keys don't contain quotes that break this
        # A safer way is using deepdiff's "extract" if available, or just re-implement simple walk
        
        # Safe extraction:
        keys = deepdiff_path.replace("root", "").replace("']['", "|").replace("['", "").replace("']", "").split("|")
        val = data
        for key in keys:
            if key: # skip empty
                val = val[key]
        return val
    except Exception:
        return "?"
