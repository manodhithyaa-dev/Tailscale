"""Unit tests for the pure helpers in ``services`` (no DB/Docker required)."""

from __future__ import annotations

from pathlib import Path

import pytest

import config
import security
import services


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SELECT 1", True),
        ("  select * from t", True),
        ("/* c */ SHOW TABLES", True),
        ("WITH x AS (SELECT 1) SELECT * FROM x", True),
        ("INSERT INTO t VALUES (1)", False),
        ("UPDATE t SET a=1", False),
        ("DELETE FROM t", False),
        ("DROP TABLE t", False),
        ("", True),
    ],
)
def test_is_read_only(query, expected):
    assert services.is_read_only(query) is expected


def _admin():
    return {"id": 1, "role": "Administrator"}


def _viewer():
    return {"id": 2, "role": "Viewer"}


def test_metadata_blocked_for_non_admin():
    with pytest.raises(security.Forbidden):
        services.assert_query_allowed("SELECT token FROM nimbus_sessions", _viewer())


def test_metadata_allowed_for_admin():
    services.assert_query_allowed("SELECT token FROM nimbus_sessions", _admin())


def test_metadata_backtick_identifier_blocked():
    # Backticks quote identifiers in MySQL; they must not be stripped.
    with pytest.raises(security.Forbidden):
        services.assert_query_allowed("SELECT * FROM `nimbus_sessions`", _viewer())


def test_metadata_hidden_inside_string_literal_is_ignored():
    # A literal mentioning the table is not an actual reference.
    services.assert_query_allowed("SELECT 'nimbus_sessions' AS label", _viewer())


def test_metadata_in_comment_is_inert():
    # Comment contents never execute, so they must not trigger a false block.
    services.assert_query_allowed("SELECT 1 /* nimbus_users */", _viewer())


def test_system_schema_blocked_for_non_admin():
    with pytest.raises(security.Forbidden):
        services.assert_query_allowed("SELECT * FROM information_schema.tables", _viewer())
    with pytest.raises(security.Forbidden):
        services.assert_query_allowed("SELECT * FROM mysql.user", _viewer())


def test_system_schema_allowed_for_admin():
    services.assert_query_allowed("SELECT * FROM information_schema.tables", _admin())


def test_file_statements_always_blocked():
    for query in (
        "SELECT 1 INTO OUTFILE '/tmp/x'",
        "SELECT 1 INTO DUMPFILE '/tmp/x'",
        "SELECT LOAD_FILE('/etc/passwd')",
        "LOAD DATA INFILE '/etc/passwd' INTO TABLE t",
    ):
        with pytest.raises(services.SqlError):
            services.assert_query_allowed(query, _viewer())
        with pytest.raises(services.SqlError):
            services.assert_query_allowed(query, _admin())


def test_dos_functions_blocked():
    for query in ("SELECT SLEEP(100)", "SELECT BENCHMARK(1000000, MD5('x'))"):
        with pytest.raises(services.SqlError):
            services.assert_query_allowed(query, _viewer())


@pytest.mark.parametrize(
    "name,expected",
    [
        ("report.pdf", "report.pdf"),
        ("../etc/passwd", "passwd"),
        ("..", "file"),
        (".", "file"),
        ("...", "file"),
        ("a/../../etc", "etc"),
        ("C:\\Users\\me\\secret.txt", "secret.txt"),
        ("", "file"),
        ("   ", "file"),
    ],
)
def test_safe_name(name, expected):
    assert services._safe_name(name) == expected


def test_safe_name_is_bounded():
    assert len(services._safe_name("x" * 500)) <= 180


def test_contained_path_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    user = {"id": 7}
    (tmp_path / "7").mkdir()
    # A path inside the user's folder is allowed.
    ok = services._contained_path(user, tmp_path / "7" / "file.txt")
    assert ok == (tmp_path / "7" / "file.txt").resolve()
    # Traversal outside is rejected.
    with pytest.raises(services.StorageError):
        services._contained_path(user, tmp_path / "7" / ".." / ".." / "evil")


def test_within_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    assert services._within_storage(tmp_path / "a" / "b.txt")
    assert not services._within_storage(tmp_path.parent / "outside.txt")
    assert not services._within_storage(Path(tmp_path))
