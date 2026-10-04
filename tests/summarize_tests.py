"""Write CI summaries without masking pytest failures."""

import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def summarize(suite, report, exit_code):
    descriptions = {
        "0": "All selected tests passed.",
        "1": "Test failures were reported. Inspect the failure details below and in the artifacts.",
        "2": "Collection or execution was interrupted.",
        "3": "Pytest encountered an internal error.",
        "4": "Pytest configuration or command usage failed.",
        "5": "No tests were collected; the suite did not validate the application.",
        "": "Tests did not run. Check checkout, dependency installation, and display setup.",
    }
    lines = [f"## {suite.title()} results", "", descriptions.get(exit_code, f"Runner failed with exit code {exit_code}."), ""]
    if report.exists():
        root = ET.parse(report).getroot()
        cases = list(root.iter("testcase"))
        failures = [case for case in cases if case.find("failure") is not None]
        errors = [case for case in cases if case.find("error") is not None]
        skipped = [case for case in cases if case.find("skipped") is not None]
        lines += [f"Reported cases: {len(cases)}. Test failures: {len(failures)}. Setup/teardown errors: {len(errors)}. Skipped: {len(skipped)}.", ""]
        if errors:
            lines += ["**Setup/teardown errors occurred.** Inspect their details before interpreting those test results.", ""]
        for case in failures + errors:
            kind = "ERROR" if case in errors else "FAIL"
            lines.append(f"- {kind} `{case.get('classname')}.{case.get('name')}`")
    else:
        lines += ["No JUnit report was produced; inspect setup/runner logs."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    message = summarize(sys.argv[1], Path(sys.argv[2]), os.environ.get("TEST_EXIT_CODE", ""))
    print(message)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(destination, "a", encoding="utf-8") as output:
            output.write(message)
