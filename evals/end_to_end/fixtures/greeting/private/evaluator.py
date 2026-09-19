import runpy

def checks(root, answer):
    module = runpy.run_path(str(root / 'greeting.py'))
    def names():
        assert module['greet'](' Nahid ') == 'Hello, Nahid!'
        assert module['greet'](' Zoë你好 ') == 'Hello, Zoë你好!'
    def blanks():
        assert module['greet']('') == 'Hello, World!'
        assert module['greet']('  \t') == 'Hello, World!'
    def regression():
        assert module['farewell'](' Name ') == 'Bye,  Name !'
    return [('trimmed_and_unicode_names', names), ('blank_default', blanks), ('farewell_preserved', regression)]
