"""Exact offline library closure and identifier-aware, source-mapped linking."""

from dataclasses import replace

import pytest

from pine2ast import parse_code
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from pine2ast.libraries.store import canonical, source_hash, strict_json


def library(name="Lib", body="export f(float x)=>x*2", version=6):
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


def root(body="plot(lib.f(close))", imports="import user/Lib/1 as lib", version=6):
    return f'//@version={version}\nindicator("root")\n{imports}\n{body}\n'


def link(body="export f(float x)=>x*2", source=None, version=6):
    return link_libraries(
        source or root(version=version),
        LibraryStore.create({"user/Lib/1": library(body=body, version=version)}),
    )


@pytest.mark.parametrize("version", [5, 6])
def test_linked_projection_is_normal_pine_with_source_provenance(version):
    out = link(version=version)
    result = parse_code(out.code)
    assert result.ok, result.diagnostics
    out.verify()
    assert out.dependency_hashes == {"user/Lib/1": source_hash(library(version=version))}
    ref = next(r for r in out.receipt()["declarations"] if r["name"] == "f")["linked_name"]
    loc = out.original_location(out.code.index(ref))
    assert loc["source"] == "user/Lib/1" and loc["line"] == 3
    loc = out.original_location(out.code.rindex(ref))
    assert loc["source"] == "<memory>" and loc["line"] == 4


def test_demo_code_is_not_imported_and_private_helpers_are_closed_over_constants():
    out = link("const float K=2\nhelper(float x)=>x*K\nexport f(float x)=>helper(x)\nplot(close)")
    assert out.code.count("plot(") == 1
    assert {r["name"] for r in out.receipt()["declarations"]} == {"f", "helper", "K"}
    assert parse_code(out.code).ok


def test_transitive_versions_and_diamond_are_deterministic():
    sources = {
        "user/A/1": library("A", "import user/Common/1 as c\nexport f(float x)=>c.f(x)+1"),
        "user/B/1": library("B", "import user/Common/1 as c\nexport f(float x)=>c.f(x)+10"),
        "user/Common/1": library("Common"),
        "user/Unused/1": library("Unused"),
    }
    source = root("plot(a.f(close)+b.f(close))", "import user/A/1 as a\nimport user/B/1 as b")
    a = link_libraries(source, LibraryStore.create(sources))
    b = link_libraries(source, LibraryStore.create(dict(reversed(list(sources.items())))))
    assert a == b
    assert set(a.dependency_hashes) == set(sources) - {"user/Unused/1"}
    assert len(a.receipt()["declarations"]) == 3
    a.verify()
    assert parse_code(a.code).ok


def test_publication_versions_can_coexist_without_name_collision():
    store = LibraryStore.create(
        {"user/Lib/1": library(), "user/Lib/2": library(body="export f(float x)=>x*3")}
    )
    out = link_libraries(
        root("plot(a.f(close)+b.f(close))", "import user/Lib/1 as a\nimport user/Lib/2 as b"), store
    )
    assert len({r["linked_name"] for r in out.receipt()["declarations"]}) == 2
    assert parse_code(out.code).ok


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_legacy_sources_cannot_acquire_library_syntax(version):
    with pytest.raises(LibraryError):
        link_libraries(root(version=version), LibraryStore.create({"user/Lib/1": library()}))


@pytest.mark.parametrize(
    "badref",
    [
        "user/Lib/0",
        "user/Lib/latest",
        "user/Lib",
        "../Lib/1",
        "https://x/Lib/1",
        "user/Lib/01",
        "user/Lib/-1",
        "user/Lib/1/extra",
    ],
)
def test_reference_has_no_latest_fallback_or_filesystem_meaning(badref):
    with pytest.raises(LibraryError):
        LibraryStore.create({badref: library()})


def test_lock_is_detached_and_tampering_is_not_accepted_by_rehashing_outer_lock():
    sources = {"user/Lib/1": library()}
    store = LibraryStore.create(sources)
    pinned = store.content_hash
    sources["user/Lib/1"] = library(body="export f(float x)=>x*999")
    assert store.source("user/Lib/1") != sources["user/Lib/1"]
    with pytest.raises(LibraryError, match="SOURCE_HASH"):
        LibraryStore.admit(store.lock(), sources, expected_hash=pinned)
    lock = store.lock()
    lock["libraries"][0]["sha256"] = source_hash(sources["user/Lib/1"])
    lock["content_hash"] = source_hash(
        canonical({k: v for k, v in lock.items() if k != "content_hash"})
    )
    with pytest.raises(LibraryError, match="LOCK_HASH"):
        LibraryStore.admit(lock, sources, expected_hash=pinned)


@pytest.mark.parametrize(
    "text", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"\xff"]
)
def test_strict_json_rejects_ambiguous_data(text):
    with pytest.raises(LibraryError):
        strict_json(text)


@pytest.mark.parametrize(
    "path", ["../outside.pine", "/tmp/file", "a//b", "a/./b", "a/../b", "C:/x", "a\\b", "a\x00b"]
)
def test_locked_paths_cannot_escape(path):
    store = LibraryStore.create({"user/Lib/1": library()})
    lock = store.lock()
    lock["libraries"][0]["path"] = path
    lock["content_hash"] = source_hash(
        canonical({k: v for k, v in lock.items() if k != "content_hash"})
    )
    with pytest.raises(LibraryError, match="PATH"):
        LibraryStore.admit(lock, dict(store._sources), expected_hash=lock["content_hash"])


def write_store(tmp_path):
    store = LibraryStore.create({"user/Lib/1": library()})
    lock = tmp_path / "libraries.lock.json"
    lock.write_bytes(canonical(store.lock()))
    file = tmp_path / store.lock()["libraries"][0]["path"]
    file.parent.mkdir(parents=True)
    file.write_text(library())
    return store, lock, file


def test_directory_store_reads_once_and_ignores_later_file_change(tmp_path):
    store, lock, file = write_store(tmp_path)
    read = LibraryStore.from_directory(lock, expected_hash=store.content_hash)
    file.write_text("corrupt")
    assert read.source("user/Lib/1") == library()
    assert link_libraries(root(), read).dependency_hashes["user/Lib/1"] == source_hash(library())
    with pytest.raises(LibraryError, match="SOURCE_HASH"):
        LibraryStore.from_directory(lock, expected_hash=store.content_hash)


@pytest.mark.parametrize("what", ["source", "parent", "lock"])
def test_symlinks_are_never_followed(tmp_path, what):
    store, lock, file = write_store(tmp_path)
    if what == "source":
        file.unlink()
        file.symlink_to(lock)
    elif what == "parent":
        folder = file.parent
        other = folder.with_name("elsewhere")
        folder.rename(other)
        folder.symlink_to(other, target_is_directory=True)
    else:
        new = lock.with_suffix(".real")
        lock.rename(new)
        lock.symlink_to(new)
    with pytest.raises(LibraryError):
        LibraryStore.from_directory(lock, expected_hash=store.content_hash)


@pytest.mark.parametrize(
    "body,code",
    [
        ("var float K=2\nexport f(float x)=>x*K", "CAPTURE"),
        ("float K=close\nexport f(float x)=>x*K", "UNBOUND"),
        ("K=2\nK:=3\nexport f(float x)=>x*K", "CAPTURE"),
        ("export f(float x)=>ROOT_ONLY+x", "UNBOUND"),
        ("export f(float x)=>input.float(2)+x", "CALL_PROFILE"),
        ("g(float x)=>input.float(2)+x\nexport f(float x)=>g(x)", "CALL_PROFILE"),
        ('export f(float x)=>request.security("S","1",x)', "CALL_PROFILE"),
        ("export f(x)=>x", "PARAMETER"),
        ("export f(array<array<float>> x)=>array.size(x)", "PARAMETER"),
        ("helper(float x)=>helper(x)\nexport f(float x)=>helper(x)", "RECURSION"),
        ("a(float x)=>b(x)\nb(float x)=>a(x)\nexport f(float x)=>a(x)", "RECURSION"),
    ],
)
def test_unsupported_or_invalid_exports_do_not_inherit_root_context(body, code):
    with pytest.raises(LibraryError, match=code):
        link(body, root("ROOT_ONLY=4\nplot(lib.f(close))"))


@pytest.mark.parametrize(
    "imports,body,code",
    [
        ("import user/Lib/1 as lib\nimport user/Lib/1 as lib", "plot(close)", "ALIAS"),
        ("import user/Lib/1 as lib", "lib=1\nplot(close)", "NAME"),
        ("import user/Lib/1 as ta", "plot(close)", "ALIAS"),
        ("import user/Lib/1 as lib", "plot(lib.private(close))", "PRIVATE"),
        ("import user/Lib/1 as lib", "plot(lib.missing(close))", "PRIVATE"),
        ("import user/Lib/1 as lib", "x=lib", "ALIAS_VALUE"),
        ("import user/Lib/2 as lib", "plot(lib.f(close))", "MISSING"),
    ],
)
def test_namespace_and_revision_errors_are_explicit(imports, body, code):
    with pytest.raises(LibraryError, match=code):
        link(source=root(body, imports))


def test_local_shadow_and_string_contents_are_not_renamed():
    out = link(
        "K=2\nhelper(float x)=>x*K\nexport f(float K)=>\n    float helper=K+1\n    helper",
        root('s="lib.f K helper"\nplot(lib.f(close))'),
    )
    assert 's="lib.f K helper"' in out.code
    assert "float helper=K+1" in out.code
    assert {r["name"] for r in out.receipt()["declarations"]} == {"f"}
    assert parse_code(out.code).ok


def test_default_alias_and_unicode_and_crlf_sources():
    store = LibraryStore.create(
        {"user/Lib/1": library(body="// привет f(x)\nexport f(float x)=>x+1").replace("\n", "\r\n")}
    )
    out = link_libraries(root('s="Привет 👋"\nplot(Lib.f(close))', "import user/Lib/1"), store)
    out.verify()
    assert parse_code(out.code).ok
    offset = out.code.index("x+1")
    assert out.original_location(offset)["line"] == 4


def test_cycle_and_mixed_version_never_fall_back():
    sources = {
        "user/A/1": library("A", "import user/B/1 as b\nexport f(float x)=>b.f(x)"),
        "user/B/1": library("B", "import user/A/1 as a\nexport f(float x)=>a.f(x)"),
    }
    with pytest.raises(LibraryError, match="CYCLE"):
        link_libraries(root(imports="import user/A/1 as lib"), LibraryStore.create(sources))
    with pytest.raises(LibraryError, match="VERSION_CONTEXT"):
        link_libraries(root(), LibraryStore.create({"user/Lib/1": library(version=5)}))


@pytest.mark.parametrize(
    "badlib",
    [
        library("Wrong"),
        '//@version=6\nindicator("Lib")\nf(float x)=>x\n',
        library(body="f(float x)=>x"),
    ],
)
def test_wrong_kind_title_or_empty_export_is_not_a_library(badlib):
    with pytest.raises(LibraryError):
        link_libraries(root(), LibraryStore.create({"user/Lib/1": badlib}))


def test_rehashed_false_projection_is_reproduced_from_original_inputs():
    out = link()
    receipt = out.receipt()
    receipt["dependencies"]["user/Lib/1"] = "sha256:" + "0" * 64
    receipt["content_hash"] = source_hash(
        canonical({k: v for k, v in receipt.items() if k != "content_hash"})
    )
    with pytest.raises(LibraryError, match="PROJECTION"):
        replace(out, _receipt=canonical(receipt)).verify()
    with pytest.raises(LibraryError, match="PROJECTION"):
        replace(out, code=out.code + "\nplot(9)").verify()


def test_unreachable_private_functions_are_not_inlined():
    out = link("bad(float x)=>input.float(8)\nexport f(float x)=>x+1")
    assert {r["name"] for r in out.receipt()["declarations"]} == {"f"}


def test_const_capture_is_not_confused_with_a_reassigned_local_shadow():
    out = link(
        "K=2\nhelper(float x)=>\n    float K=x\n    K:=K+1\n    K\nexport f(float x)=>helper(x)+K"
    )
    assert parse_code(out.code).ok
    assert {r["name"] for r in out.receipt()["declarations"]} == {"K", "helper", "f"}


@pytest.mark.parametrize(
    "source,expected",
    [
        ('//@version=6\nindicator("import u/Lib/1")\nplot(close)', False),
        ('//@version=6\nindicator("a")\n// import u/Lib/1\nplot(close)', False),
        ('//@version=6\nindicator("a")\nimport u/Lib/1\nplot(close)', True),
    ],
)
def test_import_detection_is_lexical_not_a_substring(source, expected):
    from pine2ast.libraries import has_library_imports

    assert has_library_imports(source) == expected


def test_dependency_depth_and_module_count_are_bounded():
    libs = {
        f"u/L{i}/1": library(
            f"L{i}", f"import u/L{i + 1}/1 as child\nexport f(float x)=>child.f(x)"
        )
        for i in range(25)
    }
    libs["u/L25/1"] = library("L25")
    with pytest.raises(LibraryError, match="depth"):
        link_libraries(root(imports="import u/L0/1 as lib"), LibraryStore.create(libs))
    with pytest.raises(LibraryError, match="LIMIT"):
        LibraryStore.create({f"u/L{i}/1": library(f"L{i}") for i in range(65)})


def test_store_does_not_accept_unknown_files_or_duplicate_locked_ids():
    source = {"user/Lib/1": library()}
    store = LibraryStore.create(source)
    with pytest.raises(LibraryError, match="inventory"):
        LibraryStore.admit(
            store.lock(),
            {**source, "u/Extra/1": library("Extra")},
            expected_hash=store.content_hash,
        )
    lock = store.lock()
    lock["libraries"].append({**lock["libraries"][0], "path": "other.pine"})
    lock["content_hash"] = source_hash(
        canonical({k: v for k, v in lock.items() if k != "content_hash"})
    )
    with pytest.raises(LibraryError, match="duplicate"):
        LibraryStore.admit(lock, source, expected_hash=lock["content_hash"])


def test_cli_uses_only_pinned_files_and_never_overwrites_prior_output(tmp_path):
    import json
    from pine2ast.libraries.__main__ import main

    store = LibraryStore.create({"user/Lib/1": library()})
    (tmp_path / "user/Lib").mkdir(parents=True)
    lib = tmp_path / "user/Lib/1.pine"
    lib.write_text(library())
    lock = tmp_path / "libraries.lock.json"
    lock.write_bytes(canonical(store.lock()))
    source = tmp_path / "root.pine"
    source.write_text(root())
    originals = {p: p.read_bytes() for p in (source, lib, lock)}
    args = [
        "--source",
        str(source),
        "--lock",
        str(lock),
        "--expected-lock-hash",
        store.content_hash,
        "--output",
        str(tmp_path / "out"),
    ]
    assert main(args) == 0
    output = tmp_path / "out"
    linked = link_libraries(root(), store, source_name="root.pine")
    assert (output / "linked.pine").read_text() == linked.code
    assert json.loads((output / "linkage.json").read_text()) == linked.receipt()
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 1
    assert (output / "linked.pine").read_text() == linked.code
    assert {p: p.read_bytes() for p in originals} == originals


def test_cli_rejects_changed_library_before_creating_output(tmp_path):
    from pine2ast.libraries.__main__ import main

    store = LibraryStore.create({"user/Lib/1": library()})
    (tmp_path / "user/Lib").mkdir(parents=True)
    (tmp_path / "user/Lib/1.pine").write_text(library(body="export f(float x)=>999"))
    (tmp_path / "libraries.lock.json").write_bytes(canonical(store.lock()))
    (tmp_path / "root.pine").write_text(root())
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--source",
                str(tmp_path / "root.pine"),
                "--lock",
                str(tmp_path / "libraries.lock.json"),
                "--expected-lock-hash",
                store.content_hash,
                "--output",
                str(tmp_path / "out"),
            ]
        )
    assert error.value.code == 1
    assert not (tmp_path / "out").exists()


def test_projection_cannot_be_forged_by_rehashing_metadata():
    out = link()
    receipt = out.receipt()
    receipt["projection"][0]["source_start"] = 999
    receipt["content_hash"] = source_hash(
        canonical({k: v for k, v in receipt.items() if k != "content_hash"})
    )
    with pytest.raises(LibraryError, match="PROJECTION"):
        replace(out, _receipt=canonical(receipt)).verify()


@pytest.mark.parametrize("sources", [None, [], {1: "text"}])
def test_malformed_source_container_fails_as_admission_error(sources):
    with pytest.raises(LibraryError):
        LibraryStore.create(sources)
    store = LibraryStore.create({"user/Lib/1": library()})
    with pytest.raises(LibraryError):
        LibraryStore.admit(store.lock(), sources, expected_hash=store.content_hash)


def test_end_of_expanded_identifier_maps_to_its_original_token_start():
    out = link()
    row = next(
        r
        for r in out.receipt()["projection"]
        if r["generated_end"] - r["generated_start"] > r["source_end"] - r["source_start"]
    )
    assert out.original_location(row["generated_end"] - 1)["offset"] == row["source_start"]
