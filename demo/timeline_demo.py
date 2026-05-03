"""Timeline demo — demonstrates step-by-step execution with variable tracking."""


def list_traversal():
    """Simple list traversal to show pointer/index movement."""
    arr = [3, 1, 4, 1, 5, 9, 2, 6]
    result = []

    for item in arr:
        if item > 4:
            result.append(item)

    sorted_result = sorted(result)
    total = sum(sorted_result)
    return total


def dict_merge():
    """Dict operations to show key-value changes."""
    config = {"host": "localhost", "port": 8080}
    overrides = {"port": 9090, "debug": True}

    merged = {}
    for key, value in config.items():
        merged[key] = value

    for key, value in overrides.items():
        merged[key] = value

    return merged


def fibonacci(n=8):
    """Fibonacci to show recursive state changes."""
    memo = {}
    a, b = 0, 1

    for i in range(n):
        memo[i] = a
        a, b = b, a + b

    return memo
