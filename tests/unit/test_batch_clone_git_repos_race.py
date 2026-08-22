"""
Regression tests for the concurrent-request race condition in
batch_clone_git_repos (see doc.domain.resource_lookup).

Two gunicorn worker processes can independently compute the same
deterministic resource_filepath for a repo (resource_types and
get_book_codes_for_lang both call batch_clone_git_repos synchronously)
and, without per-repo locking, race unsynchronized shutil.rmtree() +
git clone against that same path. That produces git-level collisions
and, under slower/staggered clone timing, an unhandled OSError and real
data loss. These tests reproduce that race against a local git remote
with an artificially slowed `git` on PATH standing in for a real,
non-instant network clone.
"""

import multiprocessing
import os
import shutil
import stat as stat_module
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from doc.domain.resource_lookup import batch_clone_git_repos
from filelock import FileLock

pytestmark = pytest.mark.slow


def _make_bare_repo_with_content(bare_repo_dir: Path, n_files: int) -> None:
    work_dir = bare_repo_dir.parent / "seed_work"
    subprocess.check_call(["git", "init", "--bare", "-q", str(bare_repo_dir)])
    subprocess.check_call(["git", "clone", "-q", str(bare_repo_dir), str(work_dir)])
    for i in range(n_files):
        (work_dir / f"file{i}.txt").write_text(f"content {i}\n")
    subprocess.check_call(["git", "-C", str(work_dir), "add", "-A"])
    subprocess.check_call(
        [
            "git",
            "-C",
            str(work_dir),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "commit",
            "-q",
            "-m",
            "seed",
        ]
    )
    subprocess.check_call(
        ["git", "-C", str(work_dir), "push", "-q", "origin", "HEAD:refs/heads/master"]
    )
    shutil.rmtree(work_dir)


def _install_slow_git_wrapper(bin_dir: Path, delay_seconds: float) -> str:
    real_git = shutil.which("git")
    assert real_git is not None
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(f'#!/bin/sh\nsleep {delay_seconds}\nexec "{real_git}" "$@"\n')
    wrapper.chmod(
        wrapper.stat().st_mode
        | stat_module.S_IXUSR
        | stat_module.S_IXGRP
        | stat_module.S_IXOTH
    )
    return str(bin_dir)


def _clone_worker(
    repo_url: str,
    dest: str,
    slow_git_bin_dir: str,
    barrier: Any,
    result_queue: "multiprocessing.Queue[Any]",
) -> None:
    os.environ["PATH"] = slow_git_bin_dir + os.pathsep + os.environ["PATH"]
    barrier.wait()
    try:
        skipped = batch_clone_git_repos(
            [(repo_url, dest)],  # type: ignore[list-item]
            asset_caching_enabled=False,
        )
        result_queue.put(("ok", skipped))
    except (
        Exception
    ) as exc:  # pre-fix: shutil.rmtree can raise an unhandled OSError here
        result_queue.put(("error", repr(exc)))


def test_concurrent_batch_clone_requests_do_not_corrupt_repository(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """
    Two 'requests' (separate OS processes) call batch_clone_git_repos for
    the same repo/resource_filepath at (as near as multiprocessing allows)
    the same instant, modeling two gunicorn workers racing overlapping
    resource_types/get_book_codes_for_lang calls for the same language.

    Before the fix, this reliably reproduces a git-level collision: the
    two unsynchronized `git clone` invocations race into the same
    destination path, and one of them prints a `fatal: ...` line to
    stderr (e.g. "could not create work tree dir ...: File exists" or
    "destination path ... already exists") -- confirmed by running this
    exact scenario against the pre-fix code shape, which hits this on
    every round. After the fix, the per-repo FileLock serializes the two
    clones for this path, so no such collision output appears and the
    resulting clone is complete and uncorrupted.
    """
    n_files = 12
    n_rounds = 5

    for round_num in range(n_rounds):
        bare_repo = tmp_path / f"remote_{round_num}.git"
        _make_bare_repo_with_content(bare_repo, n_files)

        slow_git_bin_dir = _install_slow_git_wrapper(
            tmp_path / f"slow_git_bin_{round_num}", delay_seconds=0.5
        )

        dest = str(tmp_path / f"dest_repo_{round_num}")
        repo_url = f"file://{bare_repo}"

        ctx = multiprocessing.get_context("fork")
        barrier = ctx.Barrier(2)
        result_queue: "multiprocessing.Queue[Any]" = ctx.Queue()
        procs = [
            ctx.Process(
                target=_clone_worker,
                args=(repo_url, dest, slow_git_bin_dir, barrier, result_queue),
            )
            for _ in range(2)
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=30)

        assert all(proc.exitcode == 0 for proc in procs), [
            proc.exitcode for proc in procs
        ]

        results = [result_queue.get(timeout=5) for _ in procs]
        for outcome, payload in results:
            assert (
                outcome == "ok"
            ), f"round {round_num}: batch_clone_git_repos raised unexpectedly: {payload}"

        captured = capfd.readouterr()
        assert (
            "fatal:" not in captured.err
        ), f"round {round_num}: git-level collision detected in stderr:\n{captured.err}"

        assert os.path.isdir(dest)
        assert os.path.isdir(os.path.join(dest, ".git"))
        tracked_files = [name for name in os.listdir(dest) if name.startswith("file")]
        assert (
            len(tracked_files) == n_files
        ), f"round {round_num}: expected {n_files} files, found {tracked_files}"


def _hold_lock_worker(lock_path: str, hold_seconds: float, ready: Any) -> None:
    lock = FileLock(lock_path, timeout=5)
    with lock:
        ready.set()
        time.sleep(hold_seconds)


def test_lock_contention_skips_cleanly_and_leaves_existing_content_untouched(
    tmp_path: Path,
) -> None:
    """
    When a repo's lock is already held (standing in for another worker's
    slow, in-flight clone of the same repo), a concurrent
    batch_clone_git_repos call must not touch that path's contents at
    all: it should skip cleanly, report the skip, and never call
    shutil.rmtree after failing to acquire the lock. This is the flaw in
    the originally drafted (never-activated) FileLock version, whose
    lock did not cover the clone and which, once the drafted lock scope
    is naively widened to cover it, has no distinct handling for
    contention -- either produces the same git-level collision, or lets
    an unhandled filelock.Timeout propagate.
    """
    dest = tmp_path / "dest_repo"
    dest.mkdir()
    for i in range(5):
        (dest / f"existing{i}.txt").write_text("pre-existing content\n")
    before = sorted(os.listdir(dest))

    lock_path = str(dest) + ".lock"
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    holder = ctx.Process(target=_hold_lock_worker, args=(lock_path, 3.0, ready))
    holder.start()
    assert ready.wait(timeout=5)

    skipped = batch_clone_git_repos(
        [("file:///nonexistent-remote.git", str(dest))],  # type: ignore[list-item]
        asset_caching_enabled=False,
        lock_timeout_seconds=1,
    )

    holder.join(timeout=10)
    assert holder.exitcode == 0

    assert skipped == [str(dest)]
    after = sorted(os.listdir(dest))
    assert after == before
