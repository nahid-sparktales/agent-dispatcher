def merge_intervals(intervals):
    if not intervals:
        return []
    intervals.sort()
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        if start < merged[-1][1]:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged
