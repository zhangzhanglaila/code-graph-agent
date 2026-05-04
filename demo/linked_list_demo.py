"""Linked list demo — pointer traversal for data structure visualization."""


class Node:
    """A node in a singly linked list."""

    def __init__(self, val):
        self.val = val
        self.next = None

    def __repr__(self):
        return f"Node({self.val})"


def build_and_traverse():
    """Build a linked list [3, 7, 1, 9, 4] and traverse it.

    This function demonstrates:
    1. Node creation with pointer linking
    2. Pointer traversal (head → tail)
    3. Value accumulation during traversal
    """
    # Phase 1: Create nodes
    n1 = Node(3)
    n2 = Node(7)
    n3 = Node(1)
    n4 = Node(9)
    n5 = Node(4)

    # Phase 2: Link nodes (pointer assignment)
    head = n1
    n1.next = n2
    n2.next = n3
    n3.next = n4
    n4.next = n5

    # Phase 3: Traverse and accumulate
    current = head
    total = 0
    visited = []

    while current is not None:
        total += current.val
        visited.append(current.val)
        current = current.next

    return {"head": head.val, "total": total, "visited": visited}


def find_max():
    """Build list [5, 2, 8, 3, 1] and find max by traversal."""
    a = Node(5)
    b = Node(2)
    c = Node(8)
    d = Node(3)
    e = Node(1)
    a.next = b
    b.next = c
    c.next = d
    d.next = e

    current = a
    max_val = current.val
    max_node = current

    while current is not None:
        if current.val > max_val:
            max_val = current.val
            max_node = current
        current = current.next

    return max_val


def reverse_list():
    """Build [1, 2, 3, 4] and reverse it by pointer manipulation."""
    a = Node(1)
    b = Node(2)
    c = Node(3)
    d = Node(4)
    a.next = b
    b.next = c
    c.next = d

    prev = None
    current = a

    while current is not None:
        next_node = current.next
        current.next = prev
        prev = current
        current = next_node

    return prev  # new head
