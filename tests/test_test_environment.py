"""Exercise test startup in a separate native process with restricted old temp paths."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.integration
def test_fresh_run_avoids_inaccessible_shared_username_directories(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    sibling_marker = tmp_path / "calling-run.txt"
    sibling_marker.write_text("keep this run", encoding="utf-8")
    environment = os.environ.copy()
    # The calling pytest run has its own override; exercise the child's default.
    environment.pop("PYTEST_DEBUG_TEMPROOT", None)
    environment.pop("PYTEST_ADDOPTS", None)
    script = textwrap.dedent(
        """
        import os
        from pathlib import Path
        import sys
        import tempfile
        from unittest.mock import patch

        import pytest

        repository = Path.cwd()
        shared_roots = (Path(tempfile.gettempdir()).resolve(), repository / ".cache" / "pytest")
        blocked_operations = []

        original_mkdir = Path.mkdir

        def guarded_mkdir(path, *args, **kwargs):
            if path.parent.resolve() in shared_roots and path.name.startswith("pytest-of-"):
                blocked_operations.append(str(path))
                raise PermissionError(13, "Simulated inaccessible shared pytest directory", str(path))
            return original_mkdir(path, *args, **kwargs)

        observed = {}

        class ObserveFixture:
            @pytest.hookimpl(tryfirst=True)
            def pytest_runtest_teardown(self, item):
                run_root = Path(os.environ["PYTEST_DEBUG_TEMPROOT"])
                fixture_path = item.funcargs["tmp_path"]
                assert run_root.parent == repository / ".cache" / "pytest"
                assert run_root.name.startswith("run-")
                assert fixture_path.is_relative_to(run_root)
                assert (fixture_path / "VERSION").read_text(encoding="utf-8") == "1.2.3\\n"
                observed["run_root"] = run_root

        # Deny shared-directory attempts regardless of whether they exist.
        with patch.object(Path, "mkdir", guarded_mkdir):
            result = pytest.main(
                ["-q", "tests/test_utility.py::test_current_version_reads_bundled_resource"],
                plugins=[ObserveFixture()],
            )
        assert result == 0, f"Child pytest failed with exit code {result}"
        assert not blocked_operations, blocked_operations
        assert "run_root" in observed, "The fixture was not inspected"
        assert not observed["run_root"].exists(), "The completed run was not cleaned up"
        assert "PYTEST_DEBUG_TEMPROOT" not in os.environ, "Temporary override leaked after pytest"
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sibling_marker.read_text(encoding="utf-8") == "keep this run"
