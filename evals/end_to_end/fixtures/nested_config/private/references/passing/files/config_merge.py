from copy import deepcopy

def merge_config(defaults, overrides):
    result = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
