from typing import List, Dict, Any

def add_interval(intervals: List[Dict[str, Any]], size: int, effect: Any) -> None:
    """
    Adds a new test result (size, effect) to the intervals list,
    handling merging and splitting as needed.
    intervals is modified in-place.
    The intervals list is assumed to be sorted by 'begin' and non-overlapping
    (except for single points that might touch, but logic aims to keep them disjoint or merged).
    """
    # 1. Check if covered by existing interval
    covered_idx = -1
    for i, interval in enumerate(intervals):
        if interval['begin'] <= size <= interval['end']:
            covered_idx = i
            break
            
    if covered_idx != -1:
        interval = intervals[covered_idx]
        if interval['effect'] == effect:
            return # Already consistent
        
        # Conflict found: Split
        old_begin = interval['begin']
        old_end = interval['end']
        old_effect = interval['effect']
        
        # Remove the conflicting interval
        del intervals[covered_idx]
        
        # Determine replacements
        # If size is strictly inside
        if old_begin < size < old_end:
            # (a, b) -> (a, a), (size, size), (b, b)
            # We insert in reverse order to keep index stable or just insert at covered_idx
            
            # (b, b)
            intervals.insert(covered_idx, {"begin": old_end, "end": old_end, "effect": old_effect})
            # (size, size)
            intervals.insert(covered_idx, {"begin": size, "end": size, "effect": effect})
            # (a, a)
            intervals.insert(covered_idx, {"begin": old_begin, "end": old_begin, "effect": old_effect})
            
        elif size == old_begin:
            # (a, b) -> (a, a) [New Effect], (b, b) [Old Effect]
            # If a==b (point interval), we just update effect (handled implicitly or separate check?)
            if old_begin == old_end:
                # Point interval update
                intervals.insert(covered_idx, {"begin": size, "end": size, "effect": effect})
            else:
                 intervals.insert(covered_idx, {"begin": old_end, "end": old_end, "effect": old_effect})
                 intervals.insert(covered_idx, {"begin": size, "end": size, "effect": effect})

        elif size == old_end:
             # (a, b) -> (a, a) [Old], (b, b) [New]
             if old_begin == old_end:
                 # Point interval update (should be caught by size==old_begin above, but for completeness)
                 intervals.insert(covered_idx, {"begin": size, "end": size, "effect": effect})
             else:
                 intervals.insert(covered_idx, {"begin": size, "end": size, "effect": effect})
                 intervals.insert(covered_idx, {"begin": old_begin, "end": old_begin, "effect": old_effect})
        
        return

    # 2. Not covered, insert and merge
    # Find insertion point
    
    idx = 0
    while idx < len(intervals) and intervals[idx]['end'] < size:
        idx += 1
        
    # idx is the index where the new interval would be (or after which)
    # intervals[idx-1].end < size
    # intervals[idx].end >= size (but we know not covered, so intervals[idx].begin > size)
    
    left_merge = False
    right_merge = False
    
    # Check left neighbor (idx-1)
    if idx > 0:
        if intervals[idx-1]['effect'] == effect:
            left_merge = True
    
    # Check right neighbor (idx)
    if idx < len(intervals):
        if intervals[idx]['effect'] == effect:
            right_merge = True
    
    if left_merge and right_merge:
        # Merge left, size, right
        # intervals[idx-1] + size + intervals[idx]
        intervals[idx-1]['end'] = intervals[idx]['end']
        del intervals[idx]
    elif left_merge:
        intervals[idx-1]['end'] = size
    elif right_merge:
        intervals[idx]['begin'] = size
    else:
        intervals.insert(idx, {"begin": size, "end": size, "effect": effect})
