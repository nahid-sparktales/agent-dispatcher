import copy
import runpy

def checks(root, answer):
    summarize=runpy.run_path(str(root/'ledger.py'))['summarize']
    def groups():
        rows=[{'category':'z','amount_cents':10},{'category':'a','amount_cents':-30},{'category':'z','amount_cents':10},{'category':'a','amount_cents':50}]
        assert summarize(rows)==[{'category':'a','count':2,'total_cents':20},{'category':'z','count':2,'total_cents':20}]
    def empty_zero_unicode():
        assert summarize([])==[]
        assert summarize([{'category':'é','amount_cents':0}])==[{'category':'é','count':1,'total_cents':0}]
    def ownership():
        rows=[{'category':'x','amount_cents':100}];original=copy.deepcopy(rows)
        result=summarize(rows)
        result[0]['category']='other'
        assert rows==original
    return [('group_and_sort',groups),('empty_zero_unicode',empty_zero_unicode),('input_ownership',ownership)]
