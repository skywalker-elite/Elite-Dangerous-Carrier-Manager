"""Run diagnostics and write CI summaries without masking pytest failures."""

import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def run_diagnostics(report, pytest_args=()):
    import pytest

    class Collection:
        deselected = 0

        def pytest_deselected(self, items):
            self.deselected += len(items)

    collection = Collection()
    status = pytest.main(
        [*pytest_args, "-m", "known_defect", f"--junitxml={report}"],
        plugins=[collection],
    )
    if status == pytest.ExitCode.NO_TESTS_COLLECTED and collection.deselected:
        print("No known-defect diagnostics remain; collected regression tests were deselected.")
        return 0
    return int(status)


def summarize(suite, report, exit_code):
    descriptions = {
        "0": "All selected tests passed.",
        "1": "Test failures were reported. Inspect the failure details below and in the artifacts.",
        "2": "Collection or execution was interrupted; this is not a known-defect result.",
        "3": "Pytest encountered an internal error.",
        "4": "Pytest configuration or command usage failed.",
        "5": "No tests were collected; the suite did not validate the application.",
        "": "Tests did not run. Check checkout, dependency installation, and display setup.",
    }
    lines = [f"## {suite.title()} results", "", descriptions.get(exit_code, f"Runner failed with exit code {exit_code}."), ""]
    if suite == "diagnostics":
        lines += ["This check is intentionally non-required. Failures remain visible; they are not converted to skips or expected passes.", ""]
    if report.exists():
        root = ET.parse(report).getroot()
        cases = list(root.iter("testcase"))
        failures = [case for case in cases if case.find("failure") is not None]
        errors = [case for case in cases if case.find("error") is not None]
        skipped = [case for case in cases if case.find("skipped") is not None]
        if suite == "diagnostics" and exit_code == "0" and not cases:
            lines[2] = "No known-defect diagnostics remain; collected regression tests were deselected."
        lines += [f"Reported cases: {len(cases)}. Test failures: {len(failures)}. Setup/teardown errors: {len(errors)}. Skipped: {len(skipped)}.", ""]
        if errors:
            lines += ["**Setup/teardown errors are not confirmed defect reproductions.** Fix the environment or test harness before interpreting those cases.", ""]
        for case in failures + errors:
            defect = next((p.get("value") for p in case.iter("property") if p.get("name") == "defect_id"), None)
            label = f"{defect}: " if defect else ""
            kind = "ERROR" if case in errors else "FAIL"
            lines.append(f"- {kind} `{label}{case.get('classname')}.{case.get('name')}`")
        if suite == "diagnostics":
            passing = [case for case in cases if case not in failures + errors + skipped]
            if passing:
                lines += ["", "Passing diagnostics should be reviewed and promoted to the regression suite:"]
                lines.extend(f"- `{case.get('classname')}.{case.get('name')}`" for case in passing)
    else:
        lines += ["No JUnit report was produced; inspect setup/runner logs."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if sys.argv[1] == "--run-diagnostics":
        raise SystemExit(run_diagnostics(Path(sys.argv[2]), sys.argv[3:]))
    message = summarize(sys.argv[1], Path(sys.argv[2]), os.environ.get("TEST_EXIT_CODE", ""))
    print(message)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(destination, "a", encoding="utf-8") as output:
            output.write(message)
