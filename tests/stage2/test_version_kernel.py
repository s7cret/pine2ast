from pine2ast.api import ParseOptions, parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.diagnostics import codes
from pine2ast.versioning import PineVersionResolver, VersionOrigin


def resolver():
    return PineVersionResolver(CatalogRepository.default().identity_tuple)


def test_annotation_resolves_exactly_once_for_every_known_version():
    for version in range(1, 7):
        result = resolver().resolve(f"//@version={version}\nstudy('x')")
        assert result.ok
        assert result.context is not None
        assert result.context.pine_version == version
        assert result.context.origin is VersionOrigin.COMPILER_ANNOTATION


def test_missing_annotation_is_v1_and_uses_v1_frontend():
    resolved = resolver().resolve("study('x')")
    assert resolved.ok and resolved.context is not None
    assert resolved.context.pine_version == 1
    parsed = parse_code("study('x')\nx = close\n")
    assert parsed.ok
    assert parsed.version_context is not None
    assert parsed.version_context.pine_version == 1
    assert any(item.code == codes.VERSION_DEFAULTED_TO_V1 for item in parsed.diagnostics)


def test_future_version_never_falls_back():
    result = resolver().resolve("//@version=7\nindicator('x')")
    assert not result.ok
    assert result.context is None
    assert any(item.code == codes.UNSUPPORTED_VERSION for item in result.diagnostics)


def test_expected_version_is_assertion_not_override():
    result = resolver().resolve("//@version=5\nindicator('x')", expected_pine_version=6)
    assert not result.ok
    assert result.context is None
    assert any(item.code == codes.VERSION_EXPECTATION_MISMATCH for item in result.diagnostics)


def test_annotation_inside_string_is_ignored():
    result = resolver().resolve("//@version=6\nindicator('x')\ns = \"//@version=5\"")
    assert result.ok and result.context is not None
    assert result.context.pine_version == 6


def test_program_carries_only_version_context():
    result = parse_code("//@version=6\nindicator('x')", ParseOptions(run_semantic=False))
    assert result.ast is not None
    assert result.ast.version_context.pine_version == 6
    assert not hasattr(result.ast, "version")
    assert not hasattr(result.ast, "language_version")
