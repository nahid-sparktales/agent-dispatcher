import runpy

def checks(root, answer):
    module = runpy.run_path(str(root / 'retrying.py'))
    retry, transient = module['retry_call'], module['TransientError']
    def succeeds():
        calls = []
        def op():
            calls.append(1)
            if len(calls)<2: raise transient('temporary')
            return {'value':42}
        assert retry(op,3) == {'value':42}
        assert len(calls) == 2
    def bounded():
        calls=[]
        error=transient('last')
        def op(): calls.append(1); raise error
        try: retry(op,2)
        except transient as actual: assert actual is error
        else: raise AssertionError('last transient not propagated')
        assert len(calls)==2
    def no_wrong_retries():
        calls=[]
        def op(): calls.append(1); raise TypeError('fatal')
        try: retry(op)
        except TypeError: pass
        else: raise AssertionError('fatal error swallowed')
        assert len(calls)==1
        for attempts in (0,-1):
            try: retry(op,attempts)
            except ValueError: pass
            else: raise AssertionError('invalid budget accepted')
        assert len(calls)==1
    return [('success_stops_calls', succeeds), ('total_attempt_budget', bounded), ('exception_and_validation', no_wrong_retries)]
