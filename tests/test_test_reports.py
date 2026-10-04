"""Check diagnostic CI status against real isolated pytest runs."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.summarize_tests import summarize


@pytest.mark.parametrize('scenario,expected_status', [
    ('promoted', 0), ('empty', 5), ('failure', 1),
    ('collection_error', 2), ('internal_error', 3), ('configuration_error', 4),
])
def test_diagnostic_runner_only_accepts_deselected_regressions(tmp_path, scenario, expected_status):
    config = tmp_path / 'pytest.ini'
    config.write_text(
        '[pytest]\naddopts = --strict-config --strict-markers\n'
        'markers =\n    known_defect(id): diagnostic\n', encoding='utf-8',
    )
    test_file = tmp_path / 'test_sample.py'
    test_file.write_text('def test_regression():\n    assert True\n', encoding='utf-8')
    if scenario == 'empty':
        test_file.write_text('', encoding='utf-8')
    elif scenario == 'failure':
        test_file.write_text(
            'import pytest\n@pytest.mark.known_defect("TEST-001")\n'
            'def test_diagnostic():\n    assert False\n', encoding='utf-8',
        )
    elif scenario == 'collection_error':
        test_file.write_text('raise RuntimeError("broken collection")\n', encoding='utf-8')
    elif scenario == 'internal_error':
        (tmp_path / 'conftest.py').write_text(
            'def pytest_collection_modifyitems(items):\n'
            '    raise RuntimeError("broken collection hook")\n', encoding='utf-8',
        )
    elif scenario == 'configuration_error':
        with config.open('a', encoding='utf-8') as stream:
            stream.write('invalid_configuration = true\n')
    report = tmp_path / 'diagnostics.xml'
    environment = os.environ.copy()
    environment.pop('PYTEST_ADDOPTS', None)
    environment['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    result = subprocess.run(
        [sys.executable, '-m', 'scripts.summarize_tests', '--run-diagnostics',
         str(report), '-c', str(config), str(test_file)],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    summary = summarize('diagnostics', report, str(result.returncode))
    assert ('No known-defect diagnostics remain' in summary) == (scenario == 'promoted')
    assert ('No known-defect diagnostics remain' in result.stdout) == (scenario == 'promoted')
