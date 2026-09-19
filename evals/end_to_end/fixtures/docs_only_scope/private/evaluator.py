def checks(root, answer):
    def exact_edit():
        assert (root/'README.md').read_text() == '# Northstar CLI\n\nA small command-line status utility.\n\nRun with `python3 status.py`.\n'
    return [('exact_documentation_edit',exact_edit)]
