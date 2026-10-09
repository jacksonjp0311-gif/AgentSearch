"""Small, deliberately non-executable checkpoint example."""

checkpoint_version = 3
receipt_policy = 'verify before promotion'

def describe_checkpoint():
    return {'version': checkpoint_version, 'policy': receipt_policy}
