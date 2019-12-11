DEPLOY_TEST_BASENAME = 'test_features.py'


def pytest_collection_modifyitems(session, config, items):
    # Ensure that all tests with require a redeploy are run after
    # tests that don't need a redeploy.
    start, end = _get_start_end_index(DEPLOY_TEST_BASENAME, items)
    marked = []
    unmarked = []
    for item in items[start:end]:
        if item.get_closest_marker('on_redeploy') is not None:
            marked.append(item)
        else:
            unmarked.append(item)
    items[start:end] = unmarked + marked


def _get_start_end_index(basename, items):
    # precondition: all the tests for test_features.py are
    # in a contiguous range.  This is the case because pytest
    # will group all tests in a module together.
    matched = [item.fspath.basename == basename for item in items]
    if not any(matched):
        return 0, len(items)
    return (
        matched.index(True),
        len(matched) - list(reversed(matched)).index(True)
    )
