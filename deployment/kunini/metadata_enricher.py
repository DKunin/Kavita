#!/usr/bin/env python3
"""Audit and safely enrich Kavita series summaries from open metadata sources.

The default ``audit`` command is read-only. ``apply`` and ``rollback`` require
the SHA-256 of their input manifest, a live drift preflight, and a verified
SQLite online backup before the first API write.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


REPORT_VERSION = 1
USER_AGENT_NAME = "KavitaKuniniMetadataEnricher/1.0"
OPEN_LIBRARY_LICENSE = "CC0-1.0"
WIKIPEDIA_LICENSE = "CC-BY-SA-4.0"
METRON_LICENSE = "CC-BY-SA-4.0"
FORMAT_NAMES = {0: "image", 1: "archive", 2: "unknown", 3: "epub", 4: "pdf"}


class EnricherError(RuntimeError):
    """An expected, operator-actionable failure."""


class HttpStatusError(EnricherError):
    """An HTTP response that callers may handle by status code."""

    def __init__(self, status_code: int, host: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} from {host}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in decomposed.casefold() if ch.isalnum())


def author_matches(expected: Iterable[str], actual: Iterable[str]) -> bool:
    expected_norm = {normalize(name) for name in expected if normalize(name)}
    actual_norm = {normalize(name) for name in actual if normalize(name)}
    return bool(expected_norm & actual_norm)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise EnricherError(f"Cannot read secret file {path}: {error}") from error
    if not value:
        raise EnricherError(f"Secret file is empty: {path}")
    return value


def summary_html(
    text: str,
    source_name: str,
    source_url: str,
    license_name: str,
    attribution: Iterable[dict[str, str]] = (),
) -> str:
    clean = plain_text(text)
    if not clean:
        return ""
    escaped_text = html.escape(clean)
    escaped_name = html.escape(source_name)
    escaped_url = html.escape(source_url, quote=True)
    escaped_license = html.escape(license_name)
    footer = f'Source: <a href="{escaped_url}">{escaped_name}</a> ({escaped_license}).'
    adapted_from: list[str] = []
    for item in attribution:
        label = plain_text(item.get("source")) or "original source"
        url = str(item.get("url", "")).strip()
        escaped_label = html.escape(label)
        if urllib.parse.urlsplit(url).scheme in {"http", "https"}:
            escaped_attribution_url = html.escape(url, quote=True)
            adapted_from.append(
                f'<a href="{escaped_attribution_url}">{escaped_label}</a>'
            )
        else:
            adapted_from.append(escaped_label)
    if adapted_from:
        footer += " Adapted from: " + ", ".join(adapted_from) + "."
    return f"<p>{escaped_text}</p><p><small>{footer}</small></p>"


@dataclasses.dataclass(frozen=True)
class Target:
    series_id: int
    title: str
    authors: tuple[str, ...]
    release_year: int
    language: str
    format: int
    isbns: tuple[str, ...]
    metron_id: int
    metadata: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class Proposal:
    provider: str
    match_kind: str
    source_id: str
    source_url: str
    license: str
    confidence: float
    text: str
    attribution: tuple[dict[str, str], ...] = ()
    auto_eligible: bool = False

    def as_dict(self) -> dict[str, Any]:
        source_name = {
            "open_library": "Open Library",
            "wikipedia": "Wikipedia",
            "metron": "Metron",
        }[self.provider]
        return {
            "provider": self.provider,
            "matchKind": self.match_kind,
            "sourceId": self.source_id,
            "sourceUrl": self.source_url,
            "license": self.license,
            "confidence": self.confidence,
            "attribution": list(self.attribution),
            "summaryHtml": summary_html(
                self.text,
                source_name,
                self.source_url,
                self.license,
                self.attribution,
            ),
            "autoEligible": self.auto_eligible,
        }


class JsonHttpClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path | None = None,
        cache_ttl_days: int = 90,
        minimum_interval: float = 0.0,
    ) -> None:
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl_days * 86400
        self.minimum_interval = minimum_interval
        self._rate_lock = threading.Lock()
        self._last_request = 0.0
        self._ssl_context = ssl.create_default_context()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cache_namespace: str | None = None,
    ) -> Any:
        cache_path = self._cache_path(cache_namespace, url)
        if cache_path and self._cache_is_fresh(cache_path):
            return json.loads(cache_path.read_text(encoding="utf-8"))
        value = self._request("GET", url, headers=headers)
        if cache_path:
            atomic_json(cache_path, value)
        return value

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: Any | None = None,
    ) -> Any:
        return self._request(method, url, headers=headers, body=body)

    def _cache_path(self, namespace: str | None, url: str) -> Path | None:
        if not namespace or not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / namespace / f"{digest}.json"

    def _cache_is_fresh(self, path: Path) -> bool:
        try:
            return time.time() - path.stat().st_mtime <= self.cache_ttl
        except OSError:
            return False

    def _wait_for_rate_limit(self) -> None:
        if self.minimum_interval <= 0:
            return
        with self._rate_lock:
            remaining = self.minimum_interval - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request = time.monotonic()

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: Any | None = None,
    ) -> Any:
        request_headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        request_headers.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        for attempt in range(3):
            self._wait_for_rate_limit()
            request = urllib.request.Request(
                url, data=data, headers=request_headers, method=method
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=45, context=self._ssl_context
                ) as response:
                    payload = response.read()
                    if not payload:
                        return None
                    return json.loads(payload.decode("utf-8"))
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                if not retryable or attempt == 2:
                    raise HttpStatusError(
                        error.code, urllib.parse.urlsplit(url).netloc
                    ) from error
                retry_after = error.headers.get("Retry-After")
                delay = min(float(retry_after), 60.0) if retry_after else 2**attempt
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == 2:
                    raise EnricherError(
                        f"Request failed for {urllib.parse.urlsplit(url).netloc}: {error}"
                    ) from error
                time.sleep(2**attempt)
        raise AssertionError("unreachable")


class KavitaClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.http = JsonHttpClient(USER_AGENT_NAME)
        self.headers = {"x-api-key": api_key}

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = urllib.parse.urljoin(self.base_url, path.lstrip("/"))
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def all_series(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self.http.request_json(
                "POST",
                self._url(
                    "/api/Series/all-v2",
                    {"pageNumber": page, "pageSize": 500, "context": 1},
                ),
                headers=self.headers,
                body={"statements": [], "combination": 0, "limitTo": 0},
            )
            if not isinstance(batch, list):
                raise EnricherError("Kavita series endpoint did not return a list")
            result.extend(batch)
            if len(batch) < 500:
                return result
            page += 1

    def metadata(self, series_id: int) -> dict[str, Any]:
        value = self.http.get(
            self._url("/api/Series/metadata", {"seriesId": series_id}),
            headers=self.headers,
        )
        if not isinstance(value, dict):
            raise EnricherError(f"Missing metadata DTO for series {series_id}")
        return value

    def volumes(self, series_id: int) -> list[dict[str, Any]]:
        value = self.http.get(
            self._url("/api/Series/volumes", {"seriesId": series_id}),
            headers=self.headers,
        )
        if not isinstance(value, list):
            raise EnricherError(f"Missing volume list for series {series_id}")
        return value

    def update_metadata(self, metadata: dict[str, Any]) -> None:
        self.http.request_json(
            "POST",
            self._url("/api/Series/metadata"),
            headers=self.headers,
            body={"seriesMetadata": metadata},
        )


class OpenLibraryProvider:
    def __init__(
        self, cache_dir: Path, contact: str, cache_ttl_days: int = 90
    ) -> None:
        self.http = JsonHttpClient(
            f"{USER_AGENT_NAME} ({contact})",
            cache_dir=cache_dir,
            cache_ttl_days=cache_ttl_days,
            minimum_interval=1.05,
        )
        self._author_results: dict[str, list[dict[str, Any]]] = {}

    def lookup(self, target: Target) -> Proposal | None:
        for isbn in target.isbns:
            proposal = self._lookup_isbn(target, isbn)
            if proposal:
                return proposal
        return self._lookup_title(target)

    def _lookup_isbn(self, target: Target, isbn: str) -> Proposal | None:
        url = f"https://openlibrary.org/isbn/{urllib.parse.quote(isbn)}.json"
        try:
            edition = self.http.get(url, cache_namespace="openlibrary")
        except HttpStatusError as error:
            if error.status_code == 404:
                return None
            raise
        if not isinstance(edition, dict):
            return None
        text = plain_text(edition.get("description"))
        work_key = ""
        works = edition.get("works") or []
        if works and isinstance(works[0], dict):
            work_key = str(works[0].get("key", ""))
        if not text and work_key:
            work = self._work(work_key)
            text = plain_text(work.get("description")) if work else ""
        if not text:
            return None
        edition_title = str(edition.get("title", ""))
        title_agrees = not edition_title or normalize(edition_title) == normalize(target.title)
        return Proposal(
            provider="open_library",
            match_kind="isbn_exact" if title_agrees else "isbn_title_mismatch",
            source_id=work_key or str(edition.get("key", isbn)),
            source_url=f"https://openlibrary.org{work_key or edition.get('key', '')}",
            license=OPEN_LIBRARY_LICENSE,
            confidence=1.0 if title_agrees else 0.9,
            text=text,
            auto_eligible=title_agrees,
        )

    def _lookup_title(self, target: Target) -> Proposal | None:
        if not target.authors:
            return None
        docs = self._by_author(target.authors[0])
        exact = [
            doc
            for doc in docs
            if normalize(str(doc.get("title", ""))) == normalize(target.title)
            and author_matches(target.authors, doc.get("author_name") or [])
        ]
        exact = _dedupe_docs(exact)
        match_kind = "title_author_unique"
        confidence = 0.98
        auto_eligible = len(exact) == 1
        candidates = exact
        if not candidates:
            candidates = [
                doc
                for doc in docs
                if difflib.SequenceMatcher(
                    None,
                    normalize(str(doc.get("title", ""))),
                    normalize(target.title),
                ).ratio()
                >= 0.92
                and author_matches(target.authors, doc.get("author_name") or [])
            ]
            candidates = sorted(
                _dedupe_docs(candidates),
                key=lambda doc: difflib.SequenceMatcher(
                    None,
                    normalize(str(doc.get("title", ""))),
                    normalize(target.title),
                ).ratio(),
                reverse=True,
            )
            match_kind = "title_author_fuzzy"
            confidence = 0.9
            auto_eligible = False
        if not candidates:
            return None

        candidate = _prefer_year(candidates, target.release_year)
        key = str(candidate.get("key", ""))
        text = plain_text(candidate.get("description"))
        if not text and key:
            work = self._work(key)
            text = plain_text(work.get("description")) if work else ""
        if not text:
            return None
        if len(exact) > 1:
            confidence = 0.93
            auto_eligible = False
            match_kind = "title_author_ambiguous"
        return Proposal(
            provider="open_library",
            match_kind=match_kind,
            source_id=key,
            source_url=f"https://openlibrary.org{key}",
            license=OPEN_LIBRARY_LICENSE,
            confidence=confidence,
            text=text,
            auto_eligible=auto_eligible,
        )

    def _by_author(self, author: str) -> list[dict[str, Any]]:
        cache_key = normalize(author)
        if cache_key in self._author_results:
            return self._author_results[cache_key]
        query = urllib.parse.urlencode(
            {
                "author": author,
                "fields": "key,title,author_name,description,first_publish_year,isbn",
                "limit": 1000,
            }
        )
        value = self.http.get(
            f"https://openlibrary.org/search.json?{query}",
            cache_namespace="openlibrary",
        )
        docs = value.get("docs", []) if isinstance(value, dict) else []
        self._author_results[cache_key] = docs if isinstance(docs, list) else []
        return self._author_results[cache_key]

    def _work(self, key: str) -> dict[str, Any] | None:
        try:
            value = self.http.get(
                f"https://openlibrary.org{key}.json", cache_namespace="openlibrary"
            )
        except HttpStatusError as error:
            if error.status_code == 404:
                return None
            raise
        return value if isinstance(value, dict) else None


class WikipediaProvider:
    def __init__(
        self, cache_dir: Path, contact: str, cache_ttl_days: int = 90
    ) -> None:
        self.http = JsonHttpClient(
            f"{USER_AGENT_NAME} ({contact})",
            cache_dir=cache_dir,
            cache_ttl_days=cache_ttl_days,
            minimum_interval=0.2,
        )

    def lookup(self, target: Target) -> Proposal | None:
        if not target.authors:
            return None
        surname = target.authors[0].split()[-1]
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f'intitle:"{target.title}" "{surname}"',
            "gsrnamespace": 0,
            "gsrlimit": 5,
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
        }
        value = self.http.get(
            "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params),
            cache_namespace="wikipedia",
        )
        pages = value.get("query", {}).get("pages", []) if isinstance(value, dict) else []
        matches: list[dict[str, Any]] = []
        for page in pages if isinstance(pages, list) else []:
            page_title = re.sub(r"\s*\([^)]*\)\s*$", "", str(page.get("title", "")))
            extract = plain_text(page.get("extract"))
            if normalize(page_title) != normalize(target.title):
                continue
            if normalize(surname) not in normalize(extract):
                continue
            if extract:
                matches.append(page)
        if len(matches) != 1:
            return None
        page = matches[0]
        return Proposal(
            provider="wikipedia",
            match_kind="page_title_author_exact",
            source_id=str(page.get("pageid", "")),
            source_url=str(page.get("fullurl", "")),
            license=WIKIPEDIA_LICENSE,
            confidence=0.95,
            text=_truncate(plain_text(page.get("extract")), 1800),
            auto_eligible=False,
        )


class MetronProvider:
    def __init__(
        self,
        cache_dir: Path,
        contact: str,
        token: str,
        cache_ttl_days: int = 90,
    ) -> None:
        self.http = JsonHttpClient(
            f"{USER_AGENT_NAME} ({contact})",
            cache_dir=cache_dir,
            cache_ttl_days=cache_ttl_days,
            minimum_interval=0.5,
        )
        self.headers = {"Authorization": f"Bearer {token}"}

    def lookup(self, target: Target) -> Proposal | None:
        if target.format != 1:
            return None
        if target.metron_id:
            detail = self._detail(target.metron_id)
            return self._proposal(detail, "metron_id_exact", 1.0, True)
        value = self.http.get(
            "https://metron.cloud/api/series/?"
            + urllib.parse.urlencode({"name": target.title}),
            headers=self.headers,
            cache_namespace="metron",
        )
        results = value.get("results", []) if isinstance(value, dict) else []
        exact = [
            item
            for item in results
            if normalize(str(item.get("name", ""))) == normalize(target.title)
        ]
        if len(exact) != 1:
            return None
        detail = self._detail(int(exact[0]["id"]))
        return self._proposal(detail, "series_title_exact", 0.96, False)

    def _detail(self, metron_id: int) -> dict[str, Any]:
        value = self.http.get(
            f"https://metron.cloud/api/series/{metron_id}/",
            headers=self.headers,
            cache_namespace="metron",
        )
        return value if isinstance(value, dict) else {}

    def _proposal(
        self,
        detail: dict[str, Any],
        match_kind: str,
        confidence: float,
        auto_eligible: bool,
    ) -> Proposal | None:
        text = plain_text(detail.get("desc"))
        if not text:
            return None
        metron_id = str(detail.get("id", ""))
        attribution = tuple(
            {
                "source": str(item.get("source", "")),
                "url": str(item.get("url", "")),
            }
            for item in detail.get("attribution", [])
            if isinstance(item, dict)
        )
        return Proposal(
            provider="metron",
            match_kind=match_kind,
            source_id=metron_id,
            source_url=f"https://metron.cloud/series/{metron_id}/",
            license=METRON_LICENSE,
            confidence=confidence,
            text=text,
            attribution=attribution,
            auto_eligible=auto_eligible,
        )


def _dedupe_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for doc in docs:
        key = str(doc.get("key", "")) or canonical_hash(doc)
        result[key] = doc
    return list(result.values())


def _prefer_year(candidates: list[dict[str, Any]], year: int) -> dict[str, Any]:
    if not year:
        return candidates[0]
    return min(
        candidates,
        key=lambda item: abs(int(item.get("first_publish_year") or year) - year),
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].rstrip() + "…"


def _is_blank_summary(metadata: dict[str, Any]) -> bool:
    return not plain_text(metadata.get("summary"))


def _build_target(
    series: dict[str, Any], metadata: dict[str, Any], volumes: list[dict[str, Any]]
) -> Target:
    isbns = {
        str(chapter.get("isbn", "")).strip()
        for volume in volumes
        for chapter in volume.get("chapters", [])
        if str(chapter.get("isbn", "")).strip()
    }
    return Target(
        series_id=int(series["id"]),
        title=str(series.get("localizedName") or series.get("name") or "").strip(),
        authors=tuple(
            str(writer.get("name", "")).strip()
            for writer in metadata.get("writers", [])
            if str(writer.get("name", "")).strip()
        ),
        release_year=int(metadata.get("releaseYear") or 0),
        language=str(metadata.get("language") or ""),
        format=int(series.get("format", 2)),
        isbns=tuple(sorted(isbns)),
        metron_id=int(series.get("metronId") or 0),
        metadata=metadata,
    )


def collect_targets(
    kavita: KavitaClient, *, workers: int = 8
) -> tuple[list[Target], dict[str, int]]:
    series = kavita.all_series()
    by_id = {int(item["id"]): item for item in series}
    metadata_by_id: dict[int, dict[str, Any]] = {}
    volumes_by_id: dict[int, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for series_id in by_id:
            futures[pool.submit(kavita.metadata, series_id)] = ("metadata", series_id)
            futures[pool.submit(kavita.volumes, series_id)] = ("volumes", series_id)
        for future in as_completed(futures):
            kind, series_id = futures[future]
            if kind == "metadata":
                metadata_by_id[series_id] = future.result()
            else:
                volumes_by_id[series_id] = future.result()

    targets = [
        _build_target(by_id[series_id], metadata_by_id[series_id], volumes_by_id[series_id])
        for series_id in sorted(by_id)
        if _is_blank_summary(metadata_by_id[series_id])
    ]
    stats = {
        "seriesTotal": len(series),
        "summariesPresent": len(series) - len(targets),
        "summariesMissing": len(targets),
    }
    return targets, stats


def disk_inventory(root: Path | None) -> dict[str, Any] | None:
    if root is None:
        return None
    if not root.is_dir():
        raise EnricherError(f"Library root does not exist: {root}")
    counts: dict[str, int] = {}
    archive_paths: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower().lstrip(".")
        if suffix not in {"epub", "pdf", "cbr", "cbz"}:
            continue
        counts[suffix] = counts.get(suffix, 0) + 1
        if suffix in {"cbr", "cbz"}:
            archive_paths.append(str(path.relative_to(root)))
    return {"counts": counts, "archivePaths": sorted(archive_paths)}


def generate_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.cache_ttl_days < 1:
        raise EnricherError("Cache TTL must be at least one day")
    kavita = KavitaClient(args.kavita_url, read_secret(args.api_key_file))
    targets, inventory_stats = collect_targets(kavita, workers=args.workers)
    if args.limit:
        targets = targets[: args.limit]

    open_library = OpenLibraryProvider(
        args.cache_dir, args.contact, args.cache_ttl_days
    )
    wikipedia = (
        None
        if args.skip_wikipedia
        else WikipediaProvider(args.cache_dir, args.contact, args.cache_ttl_days)
    )
    metron = None
    if args.metron_token_file:
        metron = MetronProvider(
            args.cache_dir,
            args.contact,
            read_secret(args.metron_token_file),
            args.cache_ttl_days,
        )

    items: list[dict[str, Any]] = []
    provider_errors: list[dict[str, Any]] = []
    for index, target in enumerate(targets, start=1):
        print(
            f"[{index}/{len(targets)}] {target.series_id}: {target.title}",
            file=sys.stderr,
        )
        proposals: list[Proposal] = []
        providers = [open_library]
        if metron:
            providers.insert(0, metron)
        if wikipedia:
            providers.append(wikipedia)
        for provider in providers:
            try:
                proposal = provider.lookup(target)
            except EnricherError as error:
                provider_errors.append(
                    {
                        "seriesId": target.series_id,
                        "provider": provider.__class__.__name__,
                        "error": str(error),
                    }
                )
                continue
            if proposal:
                proposals.append(proposal)
                if proposal.auto_eligible:
                    break
        proposal = max(proposals, key=lambda item: item.confidence) if proposals else None
        proposal_dict = proposal.as_dict() if proposal else None
        approved = bool(proposal and proposal.auto_eligible and proposal.confidence >= 0.98)
        items.append(
            {
                "seriesId": target.series_id,
                "title": target.title,
                "authors": list(target.authors),
                "releaseYear": target.release_year,
                "language": target.language,
                "format": FORMAT_NAMES.get(target.format, str(target.format)),
                "isbns": list(target.isbns),
                "metadataHash": canonical_hash(target.metadata),
                "originalMetadata": target.metadata,
                "proposal": proposal_dict,
                "approved": approved,
                "decision": "auto" if approved else "review" if proposal else "unmatched",
            }
        )

    proposed = [item for item in items if item["proposal"]]
    approved = [item for item in items if item["approved"]]
    report = {
        "schemaVersion": REPORT_VERSION,
        "generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kavitaUrl": args.kavita_url.rstrip("/"),
        "mode": "dry-run",
        "inventory": inventory_stats,
        "diskInventory": disk_inventory(args.library_root),
        "stats": {
            "targetsAudited": len(items),
            "proposals": len(proposed),
            "autoApproved": len(approved),
            "needsReview": sum(item["decision"] == "review" for item in items),
            "unmatched": sum(item["decision"] == "unmatched" for item in items),
        },
        "providerErrors": provider_errors,
        "items": items,
    }
    return report


def verified_sqlite_backup(database: Path, backup_dir: Path, prefix: str) -> Path:
    if not database.is_file():
        raise EnricherError(f"Kavita database does not exist: {database}")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"{prefix}-{timestamp}.db"
    source_connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise EnricherError(f"Backup quick_check failed: {result}")
    finally:
        source_connection.close()
        destination_connection.close()
    os.chmod(destination, 0o600)
    return destination


def _load_manifest(path: Path, expected_sha256: str) -> dict[str, Any]:
    actual = file_sha256(path)
    if actual != expected_sha256.casefold():
        raise EnricherError(
            f"Manifest SHA-256 mismatch: expected {expected_sha256}, got {actual}"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != REPORT_VERSION:
        raise EnricherError("Unsupported manifest schema version")
    return value


def apply_report(args: argparse.Namespace) -> dict[str, Any]:
    report = _load_manifest(args.report, args.confirm_sha256)
    report_url = str(report.get("kavitaUrl", "")).rstrip("/")
    target_url = args.kavita_url.rstrip("/")
    if report_url != target_url:
        raise EnricherError(
            f"Report targets {report_url or 'an unspecified server'}, not {target_url}"
        )
    approved = [
        item
        for item in report.get("items", [])
        if item.get("approved") is True and item.get("proposal", {}).get("summaryHtml")
    ]
    if not approved:
        raise EnricherError("Report contains no approved proposals")
    kavita = KavitaClient(args.kavita_url, read_secret(args.api_key_file))

    live_by_id: dict[int, dict[str, Any]] = {}
    drift: list[str] = []
    for item in approved:
        series_id = int(item["seriesId"])
        live = kavita.metadata(series_id)
        live_by_id[series_id] = live
        if canonical_hash(live) != item.get("metadataHash"):
            drift.append(f"{series_id}: metadata changed")
        elif not _is_blank_summary(live):
            drift.append(f"{series_id}: summary is no longer blank")
    if drift:
        raise EnricherError("Live drift detected; no writes performed: " + "; ".join(drift))

    backup = verified_sqlite_backup(args.database_path, args.backup_dir, "pre-enrichment")
    journal_path = args.journal or args.report.with_name(
        f"{args.report.stem}-apply-journal.json"
    )
    journal: dict[str, Any] = {
        "schemaVersion": REPORT_VERSION,
        "startedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kavitaUrl": target_url,
        "reportPath": str(args.report),
        "reportSha256": file_sha256(args.report),
        "databaseBackup": str(backup),
        "databaseBackupSha256": file_sha256(backup),
        "status": "running",
        "items": [],
    }
    atomic_json(journal_path, journal)

    try:
        for item in approved:
            series_id = int(item["seriesId"])
            before = live_by_id[series_id]
            after = copy.deepcopy(before)
            after["summary"] = item["proposal"]["summaryHtml"]
            after["summaryLocked"] = True
            kavita.update_metadata(after)
            reread = kavita.metadata(series_id)
            if reread.get("summary") != after["summary"] or not reread.get("summaryLocked"):
                raise EnricherError(f"Series {series_id} failed post-write verification")
            journal["items"].append(
                {
                    "seriesId": series_id,
                    "title": item.get("title", ""),
                    "status": "applied",
                    "originalMetadata": before,
                    "appliedMetadataHash": canonical_hash(reread),
                    "appliedSummary": reread["summary"],
                }
            )
            atomic_json(journal_path, journal)
    except Exception as error:
        journal["status"] = "partial_failure"
        journal["error"] = str(error)
        journal["finishedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_json(journal_path, journal)
        raise

    journal["status"] = "complete"
    journal["finishedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(journal_path, journal)
    return {"journal": str(journal_path), "backup": str(backup), "applied": len(approved)}


def rollback_journal(args: argparse.Namespace) -> dict[str, Any]:
    journal = _load_manifest(args.journal, args.confirm_sha256)
    journal_url = str(journal.get("kavitaUrl", "")).rstrip("/")
    target_url = args.kavita_url.rstrip("/")
    if journal_url != target_url:
        raise EnricherError(
            f"Journal targets {journal_url or 'an unspecified server'}, not {target_url}"
        )
    applied = [item for item in journal.get("items", []) if item.get("status") == "applied"]
    if not applied:
        raise EnricherError("Journal contains no applied entries")
    kavita = KavitaClient(args.kavita_url, read_secret(args.api_key_file))

    for item in applied:
        live = kavita.metadata(int(item["seriesId"]))
        if canonical_hash(live) != item.get("appliedMetadataHash"):
            raise EnricherError(
                f"Live drift detected for series {item['seriesId']}; no rollback writes performed"
            )

    backup = verified_sqlite_backup(args.database_path, args.backup_dir, "pre-rollback")
    rollback_path = args.output or args.journal.with_name(
        f"{args.journal.stem}-rollback.json"
    )
    result: dict[str, Any] = {
        "schemaVersion": REPORT_VERSION,
        "startedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sourceJournal": str(args.journal),
        "databaseBackup": str(backup),
        "status": "running",
        "items": [],
    }
    atomic_json(rollback_path, result)
    try:
        for item in reversed(applied):
            series_id = int(item["seriesId"])
            original = item["originalMetadata"]
            kavita.update_metadata(original)
            reread = kavita.metadata(series_id)
            if canonical_hash(reread) != canonical_hash(original):
                raise EnricherError(f"Series {series_id} failed rollback verification")
            result["items"].append({"seriesId": series_id, "status": "rolled_back"})
            atomic_json(rollback_path, result)
    except Exception as error:
        result["status"] = "partial_failure"
        result["error"] = str(error)
        result["finishedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_json(rollback_path, result)
        raise
    result["status"] = "complete"
    result["finishedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(rollback_path, result)
    return {
        "rollbackJournal": str(rollback_path),
        "backup": str(backup),
        "rolledBack": len(applied),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_kavita_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--kavita-url", default="https://books.kunini.ru")
        command.add_argument(
            "--api-key-file",
            type=Path,
            default=Path("/var/apps/kavita/secrets/dkunin-kover-api-key"),
        )

    audit = subparsers.add_parser("audit", help="Generate a read-only proposal report")
    add_kavita_options(audit)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--cache-dir", type=Path, required=True)
    audit.add_argument("--cache-ttl-days", type=int, default=90)
    audit.add_argument("--contact", default="https://books.kunini.ru")
    audit.add_argument("--metron-token-file", type=Path)
    audit.add_argument("--library-root", type=Path)
    audit.add_argument("--skip-wikipedia", action="store_true")
    audit.add_argument("--workers", type=int, default=8)
    audit.add_argument("--limit", type=int, default=0)

    apply_command = subparsers.add_parser("apply", help="Apply approved report entries")
    add_kavita_options(apply_command)
    apply_command.add_argument("--report", type=Path, required=True)
    apply_command.add_argument("--confirm-sha256", required=True)
    apply_command.add_argument("--database-path", type=Path, required=True)
    apply_command.add_argument("--backup-dir", type=Path, required=True)
    apply_command.add_argument("--journal", type=Path)

    rollback = subparsers.add_parser("rollback", help="Rollback a verified apply journal")
    add_kavita_options(rollback)
    rollback.add_argument("--journal", type=Path, required=True)
    rollback.add_argument("--confirm-sha256", required=True)
    rollback.add_argument("--database-path", type=Path, required=True)
    rollback.add_argument("--backup-dir", type=Path, required=True)
    rollback.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "audit":
            report = generate_report(args)
            atomic_json(args.output, report)
            print(
                json.dumps(
                    {
                        "report": str(args.output),
                        "sha256": file_sha256(args.output),
                        "stats": report["stats"],
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "apply":
            print(json.dumps(apply_report(args), ensure_ascii=False))
        else:
            print(json.dumps(rollback_journal(args), ensure_ascii=False))
    except EnricherError as error:
        print(f"metadata-enricher: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
