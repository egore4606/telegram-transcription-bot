"""Run only a copied archive script with fake Docker/date executables."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


@pytest.fixture
def archive_fixture(tmp_path):
    script = tmp_path / "save-logs.sh"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "save-logs.sh", script)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(f'''#!{sys.executable}
import os, pathlib, sys, time
root = pathlib.Path(os.environ["FAKE_ROOT"])
args = sys.argv
since, until = args[args.index("--since")+1], args[args.index("--until")+1]
with (root / "calls").open("a") as stream:
    stream.write(since + " " + until + "\\n")
if os.environ.get("FAKE_FAIL"):
    print("partial output")
    sys.exit(1)
if os.environ.get("FAKE_HOLD"):
    (root / "entered").touch()
    while not (root / "release").exists():
        time.sleep(0.005)
print("window " + since + " " + until)
''')
    date = binary / "date"
    date.write_text(f'''#!{sys.executable}
import os, pathlib, sys
root = pathlib.Path(os.environ["FAKE_ROOT"])
if "+%Y-%m-%d" in sys.argv:
    print("2026-01-02")
elif "24 hours ago" in sys.argv:
    print("2026-01-01T00:00:00Z")
else:
    counter = root / "counter"
    value = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(value))
    print("2026-01-02T00:00:%02dZ" % value)
''')
    docker.chmod(0o700)
    date.chmod(0o700)
    env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}", FAKE_ROOT=str(tmp_path))
    return tmp_path, script, env


def run(script, env):
    return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=10)


def test_archive_failure_leaves_cursor_and_archive_unchanged(archive_fixture):
    root, script, env = archive_fixture
    assert run(script, env).returncode == 0
    archive = root / "logs/bot-2026-01-02.log"
    state = root / "logs/.save-logs-state"
    before = archive.read_bytes(), state.read_bytes()
    result = run(script, dict(env, FAKE_FAIL="1"))
    assert result.returncode != 0
    assert (archive.read_bytes(), state.read_bytes()) == before
    assert not list((root / "logs").glob("*.tmp"))


def test_archive_serializes_read_export_append_and_cursor(archive_fixture):
    root, script, env = archive_fixture
    first = subprocess.Popen(["bash", str(script)], env=dict(env, FAKE_HOLD="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = None
    try:
        deadline = time.monotonic() + 5
        while not (root / "entered").exists():
            assert time.monotonic() < deadline
            time.sleep(0.005)
        second = subprocess.Popen(["bash", str(script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # The next fake date increments before export. Under the lock it cannot run yet.
        time.sleep(0.05)
        assert len((root / "calls").read_text().splitlines()) == 1
        (root / "release").touch()
        assert first.wait(timeout=5) == 0
        assert second.wait(timeout=5) == 0
    finally:
        (root / "release").touch()
        for process in (first, second):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
    calls = [line.split() for line in (root / "calls").read_text().splitlines()]
    assert len(calls) == 2
    # Cursor reuse is intentional: inclusive boundary overlap is documented.
    assert calls[1][0] == calls[0][1]
    assert (root / "logs/.save-logs-state").read_text().strip() == calls[1][1]
    assert len((root / "logs/bot-2026-01-02.log").read_text().splitlines()) == 2


def test_archive_restricts_permissions_including_existing_files(archive_fixture):
    root, script, env = archive_fixture
    log_dir = root / "logs"
    log_dir.mkdir(mode=0o755)
    archive = log_dir / "bot-2026-01-02.log"
    archive.write_text("existing\n")
    archive.chmod(0o644)
    assert run(script, env).returncode == 0
    assert log_dir.stat().st_mode & 0o777 == 0o700
    for path in (archive, log_dir / ".save-logs-state", log_dir / ".save-logs.lock"):
        assert path.stat().st_mode & 0o777 == 0o600
