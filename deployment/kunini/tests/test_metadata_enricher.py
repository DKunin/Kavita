from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metadata_enricher as enricher  # noqa: E402


def target(**overrides):
    values = {
        "series_id": 7,
        "title": "The Robots of Dawn",
        "authors": ("Isaac Asimov",),
        "release_year": 1983,
        "language": "en",
        "format": 3,
        "isbns": (),
        "metron_id": 0,
        "metadata": {"seriesId": 7, "summary": "", "summaryLocked": False},
    }
    values.update(overrides)
    return enricher.Target(**values)


class TextHelpersTests(unittest.TestCase):
    def test_plain_text_removes_markup_and_squashes_space(self):
        self.assertEqual(
            "One & two paragraphs.",
            enricher.plain_text("<p>One &amp; two</p>\n<p>paragraphs.</p>"),
        )

    def test_summary_html_escapes_content_and_attributes_source(self):
        value = enricher.summary_html(
            "A <dangerous> & useful intro.",
            "Open Library",
            "https://example.test/work?a=1&b=2",
            "CC0-1.0",
        )
        self.assertIn("A &amp; useful intro.", value)
        self.assertNotIn("<dangerous>", value)
        self.assertIn("a=1&amp;b=2", value)
        self.assertIn("CC0-1.0", value)

    def test_summary_html_includes_safe_upstream_attribution(self):
        value = enricher.summary_html(
            "A comic synopsis.",
            "Metron",
            "https://metron.cloud/series/7/",
            "CC-BY-SA-4.0",
            (
                {"source": "Publisher & creator", "url": "https://example.test/a?b=1&c=2"},
                {"source": "Unsafe link", "url": "javascript:alert(1)"},
            ),
        )
        self.assertIn("Adapted from:", value)
        self.assertIn("Publisher &amp; creator", value)
        self.assertIn("b=1&amp;c=2", value)
        self.assertNotIn('href="javascript:', value)

    def test_normalize_handles_punctuation_and_case(self):
        self.assertEqual(
            enricher.normalize("Everything’s Eventual"),
            enricher.normalize("EVERYTHING'S EVENTUAL"),
        )


class OpenLibraryTests(unittest.TestCase):
    def provider(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return enricher.OpenLibraryProvider(Path(temporary.name), "example.test")

    def test_unique_exact_title_and_author_is_auto_eligible(self):
        provider = self.provider()
        provider._by_author = mock.Mock(
            return_value=[
                {
                    "key": "/works/OL1W",
                    "title": "The Robots of Dawn",
                    "author_name": ["Isaac Asimov"],
                    "description": "A robot detective story.",
                    "first_publish_year": 1983,
                }
            ]
        )
        proposal = provider.lookup(target())
        self.assertIsNotNone(proposal)
        self.assertEqual("title_author_unique", proposal.match_kind)
        self.assertEqual(0.98, proposal.confidence)
        self.assertTrue(proposal.auto_eligible)

    def test_ambiguous_exact_title_requires_review(self):
        provider = self.provider()
        provider._by_author = mock.Mock(
            return_value=[
                {
                    "key": "/works/OL1W",
                    "title": "The Robots of Dawn",
                    "author_name": ["Isaac Asimov"],
                    "description": "First description.",
                },
                {
                    "key": "/works/OL2W",
                    "title": "The Robots of Dawn",
                    "author_name": ["Isaac Asimov"],
                    "description": "Second description.",
                },
            ]
        )
        proposal = provider.lookup(target())
        self.assertIsNotNone(proposal)
        self.assertEqual("title_author_ambiguous", proposal.match_kind)
        self.assertFalse(proposal.auto_eligible)

    def test_isbn_title_mismatch_is_not_auto_eligible(self):
        provider = self.provider()
        provider.http = mock.Mock()
        provider.http.get.return_value = {
            "key": "/books/OL1M",
            "title": "A Different Book",
            "description": "Description from an exact ISBN edition.",
        }
        proposal = provider.lookup(target(isbns=("9780000000001",)))
        self.assertIsNotNone(proposal)
        self.assertEqual("isbn_title_mismatch", proposal.match_kind)
        self.assertFalse(proposal.auto_eligible)

    def test_isbn_not_found_falls_back_without_provider_error(self):
        provider = self.provider()
        provider.http = mock.Mock()
        provider.http.get.side_effect = enricher.HttpStatusError(404, "openlibrary.org")
        provider._lookup_title = mock.Mock(return_value=None)
        self.assertIsNone(provider.lookup(target(isbns=("9780000000001",))))

    def test_isbn_provider_failure_is_not_hidden(self):
        provider = self.provider()
        provider.http = mock.Mock()
        provider.http.get.side_effect = enricher.HttpStatusError(503, "openlibrary.org")
        with self.assertRaisesRegex(enricher.HttpStatusError, "HTTP 503"):
            provider.lookup(target(isbns=("9780000000001",)))


class WikipediaTests(unittest.TestCase):
    def test_exact_page_title_and_author_is_review_only(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        provider = enricher.WikipediaProvider(Path(temporary.name), "example.test")
        provider.http = mock.Mock()
        provider.http.get.return_value = {
            "query": {
                "pages": [
                    {
                        "pageid": 42,
                        "title": "The Robots of Dawn (novel)",
                        "extract": "The Robots of Dawn is a novel by Isaac Asimov.",
                        "fullurl": "https://en.wikipedia.org/wiki/The_Robots_of_Dawn",
                    }
                ]
            }
        }
        proposal = provider.lookup(target())
        self.assertIsNotNone(proposal)
        self.assertEqual("page_title_author_exact", proposal.match_kind)
        self.assertFalse(proposal.auto_eligible)


class SafetyTests(unittest.TestCase):
    def test_audit_rejects_non_positive_cache_ttl(self):
        with self.assertRaisesRegex(enricher.EnricherError, "at least one day"):
            enricher.generate_report(argparse.Namespace(cache_ttl_days=0))

    def test_verified_backup_passes_quick_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "kavita.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('kept')")
            connection.commit()
            connection.close()

            backup = enricher.verified_sqlite_backup(database, root / "backups", "test")
            copied = sqlite3.connect(backup)
            self.assertEqual("kept", copied.execute("SELECT value FROM sample").fetchone()[0])
            self.assertEqual("ok", copied.execute("PRAGMA quick_check").fetchone()[0])
            copied.close()
            self.assertEqual(0o600, backup.stat().st_mode & 0o777)

    def test_apply_rejects_live_drift_before_backup_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            api_key = root / "api-key"
            api_key.write_text("secret\n", encoding="utf-8")
            original = {"seriesId": 7, "summary": "", "summaryLocked": False}
            report = {
                "schemaVersion": enricher.REPORT_VERSION,
                "kavitaUrl": "https://example.test",
                "items": [
                    {
                        "seriesId": 7,
                        "title": "Test",
                        "metadataHash": enricher.canonical_hash(original),
                        "approved": True,
                        "proposal": {"summaryHtml": "<p>Proposed.</p>"},
                    }
                ],
            }
            enricher.atomic_json(report_path, report)
            args = argparse.Namespace(
                report=report_path,
                confirm_sha256=enricher.file_sha256(report_path),
                kavita_url="https://example.test",
                api_key_file=api_key,
                database_path=root / "missing.db",
                backup_dir=root / "backups",
                journal=None,
            )
            fake = mock.Mock()
            fake.metadata.return_value = {
                "seriesId": 7,
                "summary": "Someone edited this.",
                "summaryLocked": True,
            }
            with mock.patch.object(enricher, "KavitaClient", return_value=fake):
                with mock.patch.object(enricher, "verified_sqlite_backup") as backup:
                    with self.assertRaisesRegex(enricher.EnricherError, "Live drift"):
                        enricher.apply_report(args)
            backup.assert_not_called()
            fake.update_metadata.assert_not_called()

    def test_apply_rejects_report_for_another_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            report = {
                "schemaVersion": enricher.REPORT_VERSION,
                "kavitaUrl": "https://other.example.test",
                "items": [],
            }
            enricher.atomic_json(report_path, report)
            args = argparse.Namespace(
                report=report_path,
                confirm_sha256=enricher.file_sha256(report_path),
                kavita_url="https://example.test",
            )
            with self.assertRaisesRegex(enricher.EnricherError, "another server|not"):
                enricher.apply_report(args)

    def test_apply_changes_only_summary_and_lock_then_journals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            journal_path = root / "journal.json"
            api_key = root / "api-key"
            backup_path = root / "backup.db"
            api_key.write_text("secret\n", encoding="utf-8")
            backup_path.write_bytes(b"verified backup")
            original = {
                "seriesId": 7,
                "summary": "",
                "summaryLocked": False,
                "writers": [{"name": "Isaac Asimov"}],
                "releaseYear": 1983,
            }
            proposed_summary = "<p>A robot detective story.</p>"
            report = {
                "schemaVersion": enricher.REPORT_VERSION,
                "kavitaUrl": "https://example.test",
                "items": [
                    {
                        "seriesId": 7,
                        "title": "The Robots of Dawn",
                        "metadataHash": enricher.canonical_hash(original),
                        "approved": True,
                        "proposal": {"summaryHtml": proposed_summary},
                    }
                ],
            }
            enricher.atomic_json(report_path, report)
            args = argparse.Namespace(
                report=report_path,
                confirm_sha256=enricher.file_sha256(report_path),
                kavita_url="https://example.test",
                api_key_file=api_key,
                database_path=root / "kavita.db",
                backup_dir=root / "backups",
                journal=journal_path,
            )

            class StatefulKavita:
                def __init__(self):
                    self.value = dict(original)

                def metadata(self, series_id):
                    self.series_id = series_id
                    return json.loads(json.dumps(self.value))

                def update_metadata(self, metadata):
                    self.value = json.loads(json.dumps(metadata))

            fake = StatefulKavita()
            with mock.patch.object(enricher, "KavitaClient", return_value=fake):
                with mock.patch.object(
                    enricher, "verified_sqlite_backup", return_value=backup_path
                ):
                    result = enricher.apply_report(args)

            expected = dict(original)
            expected["summary"] = proposed_summary
            expected["summaryLocked"] = True
            self.assertEqual(expected, fake.value)
            self.assertEqual(1, result["applied"])
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual("complete", journal["status"])
            self.assertEqual("applied", journal["items"][0]["status"])

    def test_manifest_sha_is_mandatory(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text('{"schemaVersion": 1}\n', encoding="utf-8")
            wrong = hashlib.sha256(b"different").hexdigest()
            with self.assertRaisesRegex(enricher.EnricherError, "mismatch"):
                enricher._load_manifest(path, wrong)

    def test_rollback_rejects_journal_for_another_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal_path = root / "journal.json"
            journal = {
                "schemaVersion": enricher.REPORT_VERSION,
                "kavitaUrl": "https://other.example.test",
                "items": [],
            }
            enricher.atomic_json(journal_path, journal)
            args = argparse.Namespace(
                journal=journal_path,
                confirm_sha256=enricher.file_sha256(journal_path),
                kavita_url="https://example.test",
            )
            with self.assertRaisesRegex(enricher.EnricherError, "Journal targets"):
                enricher.rollback_journal(args)

    def test_disk_inventory_lists_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Book.epub").touch()
            (root / "Comic.CBR").touch()
            inventory = enricher.disk_inventory(root)
            self.assertEqual({"epub": 1, "cbr": 1}, inventory["counts"])
            self.assertEqual(["Comic.CBR"], inventory["archivePaths"])


class DailyAutomationTests(unittest.TestCase):
    wrapper = Path(__file__).resolve().parents[1] / "metadata-enricher-daily.sh"

    def run_daily(self, root: Path, *, approved: int, provider_errors: int):
        fake_enricher = root / "fake_enricher.py"
        fake_enricher.write_text(
            textwrap.dedent(
                """
                import json
                import os
                import sys
                from pathlib import Path

                def option(name):
                    return sys.argv[sys.argv.index(name) + 1]

                if sys.argv[1] == "audit":
                    report = {
                        "providerErrors": ["failed"] * int(os.environ["FAKE_PROVIDER_ERRORS"]),
                        "stats": {"autoApproved": int(os.environ["FAKE_APPROVED"])},
                    }
                    output = Path(option("--output"))
                    output.write_text(json.dumps(report), encoding="utf-8")
                    print(json.dumps({"report": str(output)}))
                elif sys.argv[1] == "apply":
                    report = json.loads(Path(option("--report")).read_text(encoding="utf-8"))
                    count = report["stats"]["autoApproved"]
                    journal = {
                        "schemaVersion": 1,
                        "status": "complete",
                        "items": [{"status": "applied"}] * count,
                    }
                    Path(option("--journal")).write_text(json.dumps(journal), encoding="utf-8")
                    Path(os.environ["FAKE_APPLY_MARKER"]).write_text("applied", encoding="utf-8")
                    print(json.dumps({"applied": count}))
                else:
                    raise SystemExit(2)
                """
            ).lstrip(),
            encoding="utf-8",
        )
        api_key = root / "api-key"
        database = root / "kavita.db"
        library = root / "library"
        state = root / "state"
        marker = root / "apply-marker"
        api_key.write_text("secret\n", encoding="utf-8")
        database.touch()
        library.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "FAKE_APPROVED": str(approved),
                "FAKE_PROVIDER_ERRORS": str(provider_errors),
                "FAKE_APPLY_MARKER": str(marker),
                "KAVITA_METADATA_PYTHON": sys.executable,
                "KAVITA_METADATA_FLOCK": "/usr/bin/true",
                "KAVITA_METADATA_ENRICHER": str(fake_enricher),
                "KAVITA_METADATA_STATE_DIR": str(state),
                "KAVITA_METADATA_API_KEY_FILE": str(api_key),
                "KAVITA_METADATA_DATABASE_PATH": str(database),
                "KAVITA_METADATA_LIBRARY_ROOT": str(library),
                "KAVITA_METADATA_KAVITA_URL": "https://example.test",
            }
        )
        result = subprocess.run(
            ["/bin/bash", str(self.wrapper)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        return result, state, marker

    def test_no_candidates_is_successful_no_op(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, state, marker = self.run_daily(
                Path(temporary), approved=0, provider_errors=0
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(marker.exists())
            self.assertIn("outcome=no-op", (state / "daily.log").read_text())
            self.assertEqual(0o600, (state / "daily.log").stat().st_mode & 0o777)

    def test_provider_error_blocks_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, state, marker = self.run_daily(
                Path(temporary), approved=1, provider_errors=1
            )
            self.assertEqual(1, result.returncode)
            self.assertFalse(marker.exists())
            self.assertIn("outcome=blocked", (state / "daily.log").read_text())

    def test_candidates_are_applied_and_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, state, marker = self.run_daily(
                Path(temporary), approved=2, provider_errors=0
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(marker.exists())
            self.assertIn("outcome=complete applied=2", (state / "daily.log").read_text())
            self.assertTrue((state / "latest-journal.json").resolve().is_file())


if __name__ == "__main__":
    unittest.main()
