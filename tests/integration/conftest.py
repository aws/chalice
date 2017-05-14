def pytest_collection_modifyitems(session, config, items):
    # Ensure that all tests with require a redeploy are run after
    # tests that don't need a redeploy.
    final_list = []
    on_redeploy_tests = []
    for item in items:
        if item.get_marker('on_redeploy') is not None:
            on_redeploy_tests.append(item)
        else:
            final_list.append(item)
    final_list.extend(on_redeploy_tests)
    items[:] = final_list
