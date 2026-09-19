import copy
import runpy

def checks(root, answer):
    merge = runpy.run_path(str(root / 'intervals.py'))['merge_intervals']
    def tuples(items): return [tuple(x) for x in items]
    def nested():
        assert tuples(merge([[1,10],[2,3],[4,8]])) == [(1,10)]
        assert tuples(merge([(5,7),(1,4),(4,5),(20,22)])) == [(1,7),(20,22)]
    def ordering():
        assert tuples(merge([[3,3],[1,1],[1,2],[2,3]])) == [(1,3)]
        assert merge([]) == []
    def no_mutation():
        source = [[8,9],[1,5],[2,7]]
        original = copy.deepcopy(source)
        result = merge(source)
        assert source == original, 'input mutated'
        if result and isinstance(result[0], list): result[0][0] = -100
        assert source == original, 'returned list aliases input'
    return [('nested_and_touching', nested), ('sorted_and_empty', ordering), ('input_ownership', no_mutation)]
