def summarize(rows):
    groups = {}
    for row in rows:
        group = groups.setdefault(row['category'], {'category':row['category'], 'count':0, 'total_cents':0})
        group['count'] += 1
        group['total_cents'] += row['amount_cents']
    return [groups[key] for key in sorted(groups)]
