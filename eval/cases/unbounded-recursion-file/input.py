import json


def flatten(node, prefix=""):
    items = {}
    if isinstance(node, dict):
        for key, value in node.items():
            items.update(flatten(value, f"{prefix}{key}."))
    else:
        items[prefix.rstrip(".")] = node
    return items


def handle_upload(request_body):
    return flatten(json.loads(request_body))
