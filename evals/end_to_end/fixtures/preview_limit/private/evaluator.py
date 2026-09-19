import runpy

def checks(root, answer):
    preview = runpy.run_path(str(root / 'preview.py'))['preview']
    def truncation():
        assert preview('abcdefghij', 6) == 'abc...'
        assert preview('a'*21) == 'a'*17 + '...'
    def bounds():
        for limit in (0,1,2):
            assert preview('abcdef', limit) == 'abcdef'[:limit]
        assert preview('abcdef', 3) == '...'
        assert preview('abc', 3) == 'abc'
        assert preview('', 0) == ''
    def negative():
        try: preview('abc', -1)
        except ValueError: pass
        else: raise AssertionError('negative limit accepted')
    return [('bounded_truncation', truncation), ('boundary_limits', bounds), ('negative_limit', negative)]
