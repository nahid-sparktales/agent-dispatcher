import copy
import runpy

def checks(root, answer):
    merge=runpy.run_path(str(root/'config_merge.py'))['merge_config']
    def nesting():
        assert merge({'db':{'host':'local','port':7},'x':1},{'db':{'port':8},'y':2})=={'db':{'host':'local','port':8},'x':1,'y':2}
        assert merge({}, {})=={}
    def replacements():
        assert merge({'a':[1,2],'b':{'x':1},'c':2},{'a':[3],'b':None,'c':{'y':4}})=={'a':[3],'b':None,'c':{'y':4}}
    def ownership():
        left={'nested':{'items':[1]}};right={'extra':{'items':[2]}}
        original=copy.deepcopy((left,right));result=merge(left,right)
        result['nested']['items'].append(3);result['extra']['items'].append(4)
        assert (left,right)==original
    return [('recursive_merge',nesting),('override_replacements',replacements),('independent_data',ownership)]
