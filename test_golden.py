import os
import contextlib
import io
import json
import pytest
from translator import LispCompiler, LispParser
from machine import simulate


@pytest.mark.golden_test("tests/*.yml")
def test_pipeline(golden, tmpdir, capsys):
    source_path = os.path.join(tmpdir, "source.lisp")
    bin_path = os.path.join(tmpdir, "out.bin")

    source_code = golden["source_code"]
    with open(source_path, "w") as f:
        f.write(source_code)

    parser = LispParser(source_code)
    compiler = LispCompiler()
    binary, debug = compiler.compile(parser.parse_program())
    with open(bin_path, "wb") as f:
        f.write(binary)

    schedule_str = golden.get("schedule", "[]")
    schedule = json.loads(schedule_str)

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        simulate(binary, schedule)

    log_output = stdout.getvalue()

    if len(log_output) > 5000:
        log_output = log_output[:2000] + "\n... [TRUNCATED LOG] ...\n" + log_output[-2000:]

    assert log_output == golden.out.get("expected_log")