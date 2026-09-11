"""A scoped preview must select the same declaration after token projection.

These are semantic regression fixtures, not external TradingView executions.
"""

import pytest
from pine2ast.api import ParseOptions, ParsePipeline
from pine2ast.ast.nodes import MethodDeclaration
from pine2ast.libraries import LibraryStore, link_libraries


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("named", [False, True])
def test_private_more_specific_overload_cannot_replace_public_selection(version, reverse, named):
    private = "method pick(simple int self,int step)=>self+step+1000"
    public = "export method pick(simple int self,float step)=>self+step+100"
    rows = [private, public]
    if reverse:
        rows.reverse()
    library = f'//@version={version}\nlibrary("M")\n' + "\n".join(rows) + "\n"
    argument = "step=1" if named else "1"
    root = (
        f'//@version={version}\nindicator("scope")\nimport u/M/1 as m\n'
        f"n=2\nplot(n.pick({argument}))\n"
    )
    linked = link_libraries(root, LibraryStore.create({"u/M/1": library}))
    result = ParsePipeline(ParseOptions(library_context=linked.qualifier_context())).parse(
        linked.code
    )
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    methods = [n for n in result.ast.items if isinstance(n, MethodDeclaration)]
    assert len(methods) == 2
    assert len({n.name for n in methods}) == 2
    public_method = next(n for n in methods if n.parameters[0].type_ref.name == "float")
    # Inspect the actual final frontend binding, not the preview's success flag.
    model = result.semantic_model
    call = next(c for c in model.semantic_facts.calls if c.call_form == "USER_METHOD")
    selected = model.method_candidates.by_symbol[call.symbol_id].declaration
    assert selected is public_method
    linked.verify()


@pytest.mark.parametrize("version", [5, 6])
def test_private_selection_inside_library_and_public_selection_outside_are_distinct(version):
    library = (
        f'//@version={version}\nlibrary("M")\n'
        "method pick(simple int self,int step)=>self+step+1000\n"
        "export method pick(simple int self,float step)=>self+step+100\n"
        "export method inside(simple int self)=>self.pick(1)\n"
    )
    root = (
        f'//@version={version}\nindicator("scope")\nimport u/M/1 as m\n'
        "n=2\nplot(n.pick(1))\nplot(n.inside())\n"
    )
    linked = link_libraries(root, LibraryStore.create({"u/M/1": library}))
    result = ParsePipeline(ParseOptions(library_context=linked.qualifier_context())).parse(
        linked.code
    )
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    methods = [n for n in result.ast.items if isinstance(n, MethodDeclaration)]
    assert len({n.name for n in methods}) == 3
    facts = result.semantic_model.semantic_facts.calls
    picks = [c for c in facts if c.call_form == "USER_METHOD" and c.callee.endswith("_pick")]
    assert len(picks) == 2 and len({c.symbol_id for c in picks}) == 2
    linked.verify()
