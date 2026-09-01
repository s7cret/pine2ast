from pine2ast.semantic.completeness import pinned_catalog_static_completeness


def test_all_six_pinned_catalogs_are_internally_complete_for_declared_scope():
    for version in range(1, 7):
        report = pinned_catalog_static_completeness(version)
        assert report.ok, report.gaps
        assert report.coverage_ratio == 1.0
        assert report.symbol_count > 0
        assert report.callable_count > 0
        assert report.operator_count > 0
        if version <= 4:
            assert report.status == "HISTORICAL_STATIC_SNAPSHOT"
            assert report.scope == "documented_historical_static_snapshot"
        else:
            assert report.status == "STATIC_COMPLETE"
            assert report.scope == "pinned_hash_bound_reference_catalog"
