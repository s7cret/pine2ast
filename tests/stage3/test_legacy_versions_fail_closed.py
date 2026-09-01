from pine2ast import parse_code


def test_v1_to_v4_are_native_version_bound_frontends():
    for version in range(1, 5):
        prefix = "" if version == 1 else f"//@version={version}\n"
        result = parse_code(prefix + "study('x')\nx = close\n")
        assert result.version_context is not None
        assert result.version_context.pine_version == version
        assert result.ok, [(item.code, item.message) for item in result.diagnostics]
        assert result.ast is not None
        assert result.ast.version_context == result.version_context
        assert result.semantic_model is not None
        assert result.semantic_model.version_context == result.version_context
