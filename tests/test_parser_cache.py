#!/usr/bin/env python3
"""Offline regressions for authenticated incremental source and AST reuse."""
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import context
import parser_cache


class ParserCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.directory = self.root / "private-cache"
        self.write("main.py", "def validate_token():\n    return 1\n")

    def write(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def cache(self, **kwargs):
        return parser_cache.Cache(self.project, directory=self.directory, **kwargs)

    def read(self, cache, path="main.py", remaining=32 * 1024 * 1024, redact=lambda value: value):
        return cache.read(path, remaining, context._read, redact)

    def warm(self):
        cache = self.cache(writable=True)
        text, _, reason, _ = self.read(cache)
        self.assertIsNone(reason)
        cache.parse("main.py", text)
        cache.finish()
        self.assertEqual(cache.stats["writes"], 1)
        return cache

    def test_cold_then_warm_avoids_source_read(self):
        cold = self.warm()
        warm = self.cache(writable=True)
        # Read cache records at construction, then prove the source hit needs no read.
        with mock.patch.object(parser_cache.os, "read", side_effect=AssertionError("source reread")):
            text, used, reason, sha = self.read(warm)
        tree = warm.parse("main.py", text)
        self.assertEqual(used, len(text.encode()))
        self.assertEqual(sha, hashlib.sha256(text.encode()).hexdigest())
        self.assertIsNone(reason)
        self.assertEqual(ast.dump(tree), ast.dump(ast.parse(text)))
        self.assertEqual(warm.stats["source_hits"], 1)
        self.assertEqual(warm.stats["source_bytes_read"], 0)
        stamp = (self.directory / cold.name).stat().st_mtime_ns
        warm.finish()
        self.assertEqual(warm.stats["writes"], 0)
        self.assertEqual((self.directory / cold.name).stat().st_mtime_ns, stamp)

    def test_same_size_edit_with_restored_mtime_invalidates_using_ctime(self):
        self.warm()
        source = self.project / "main.py"
        before = source.stat()
        source.write_text(source.read_text().replace("return 1", "return 2"))
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        cache = self.cache()
        text, _, reason, _ = self.read(cache)
        cache.parse("main.py", text)
        self.assertIsNone(reason)
        self.assertIn("return 2", text)
        self.assertEqual(cache.stats["source_hits"], 0)
        self.assertEqual(cache.stats["parsed_files"], 1)

    def test_oversized_record_follows_a_same_size_edit_with_restored_mtime(self):
        body = "def alpha_handler_one():\n    return 1\n" + "# filler line to pass the read limit\n" * 8000
        source = self.write("big.py", body)

        def record(writable=False):
            cache, structural = self.cache(writable=writable), {}
            context._scan_sources(self.project, ["big.py"], (), [], cache, lambda value: value, [], [], [], structural)
            cache.finish()
            return structural["big.py"]["record"]

        self.assertEqual([row[0] for row in record(writable=True)["defs"]], ["alpha_handler_one"])
        load = context._sibling
        with mock.patch.object(context, "_sibling", lambda name: {"file_record": mock.Mock(side_effect=AssertionError("reparsed"))}
                               if name == "repo_index" else load(name)):
            self.assertEqual(record()["coverage"], "complete")  # Unchanged: the cached lexical record is reused, not reparsed.
        before = source.stat()
        source.write_text(body.replace("alpha_handler_one", "gamma_handler_two"))
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(source.stat().st_size, before.st_size)
        fresh = record()
        self.assertEqual([row[0] for row in fresh["defs"]], ["gamma_handler_two"])
        self.assertNotIn("alpha", fresh["terms"])
        # With a coarse ctime the edit keeps the key: the digest of the bytes just read still refuses the cached record.
        real = context._signature
        with mock.patch.object(context, "_signature", lambda info: real(info)[:4] + [0] + real(info)[5:]):
            self.assertEqual([row[0] for row in record(writable=True)["defs"]], ["gamma_handler_two"])
            before = source.stat()
            source.write_text(body.replace("alpha_handler_one", "delta_handler_six"))
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual([row[0] for row in record()["defs"]], ["delta_handler_six"])

    def test_large_binary_is_named_binary_from_a_bounded_sniff(self):
        (self.project / "blob.bin").write_bytes(b"\0" + b"x" * (300 * 1024))
        (self.project / "big.txt").write_text("x\n" * (200 * 1024))
        for cache in (self.cache(), self.cache(enabled=False)):  # The cache, then its fallback reader (context._read).
            self.assertEqual(self.read(cache, "blob.bin")[1:3], (0, "binary file withheld"))  # Sniffed, never charged to the scan.
            self.assertEqual(self.read(cache, "big.txt")[1:3], (0, "file exceeds 256 KiB limit"))
        cache = self.cache()
        self.read(cache, "blob.bin")
        self.assertEqual(cache.stats["source_bytes_read"], parser_cache.SNIFF_BYTES)  # The bytes actually read are still reported.

    def test_sniffs_of_large_files_never_spend_the_source_scan_budget(self):
        (self.project / "assets").mkdir()
        for number in range(4):
            (self.project / f"assets/{number}.bin").write_bytes(b"\0" * (300 * 1024))
        paths = [f"assets/{number}.bin" for number in range(4)] + ["main.py"]
        for incremental in (None, self.cache()):  # context._read, then the parser cache's own read.
            with self.subTest(cache=incremental is not None):
                excluded, diagnostics = [], []
                with mock.patch.object(context, "MAX_SCAN_BYTES", 3 * context.SNIFF_BYTES):
                    texts = context._scan_sources(self.project, paths, (), [], incremental, lambda value: value, excluded, diagnostics)[0]
                self.assertEqual(list(texts), ["main.py"])
                self.assertEqual(diagnostics, [])
                self.assertEqual([item["reason"] for item in excluded], ["binary file withheld"] * 4)

    def test_only_changed_source_is_read_again(self):
        self.write("other.py", "def other(): return 1\n")
        initial = self.cache(writable=True)
        for path in ("main.py", "other.py"):
            initial.parse(path, self.read(initial, path)[0])
        initial.finish()
        self.write("other.py", "def other(): return 2\n")
        following = self.cache()
        for path in ("main.py", "other.py"):
            following.parse(path, self.read(following, path)[0])
        self.assertEqual(following.stats["source_hits"], 1)
        self.assertEqual(following.stats["source_misses"], 1)
        self.assertEqual(following.stats["parsed_files"], 2)  # Trees are always parsed fresh.

    def test_readonly_cold_does_not_create_state_and_warm_does_not_touch_it(self):
        readonly = self.cache()
        readonly.parse("main.py", self.read(readonly)[0])
        readonly.finish()
        self.assertFalse(self.directory.exists())
        initial = self.warm()
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.directory.iterdir()}
        readonly = self.cache()
        readonly.parse("main.py", self.read(readonly)[0])
        self.write("new.py", "def added(): pass\n")
        readonly.parse("new.py", self.read(readonly, "new.py")[0])
        readonly.finish()
        after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.directory.iterdir()}
        self.assertEqual(before, after)

    def test_disabling_cache_forces_independent_read_and_parse(self):
        self.warm()
        cache = self.cache(enabled=False, writable=True)
        text, _, reason, _ = self.read(cache)
        cache.parse("main.py", text)
        cache.finish()
        self.assertIsNone(reason)
        self.assertEqual(cache.stats["source_hits"], 0)
        self.assertEqual(cache.stats["parsed_files"], 1)
        self.assertGreater(cache.stats["source_bytes_read"], 0)
        self.assertEqual(cache.stats["writes"], 0)

    def test_tampered_record_cannot_supply_source_or_facts(self):
        initial = self.warm()
        record = self.directory / initial.name
        envelope = json.loads(record.read_text())
        for value in envelope["payload"]["entries"].values():
            if isinstance(value, dict) and "text" in value:
                value["text"] = "forged_cache_authority"
        record.write_text(json.dumps(envelope))
        before = record.read_bytes()
        cache = self.cache(writable=True)
        self.assertNotIn("forged_cache_authority", self.read(cache)[0])
        cache.put("facts", "x", [{"claim": "new"}])
        cache.finish()
        self.assertEqual(record.read_bytes(), before)
        self.assertEqual(cache.stats["source_hits"], 0)

    def test_policy_change_invalidates_source_and_parse_records(self):
        self.warm()
        with mock.patch.object(parser_cache, "_policy", return_value="new-policy"):
            cache = self.cache()
            cache.parse("main.py", self.read(cache)[0])
        self.assertEqual(cache.stats["source_hits"], 0)
        self.assertEqual(cache.stats["parsed_files"], 1)

    def test_selected_redaction_policy_change_invalidates_old_redacted_source(self):
        initial = self.cache(writable=True, policy_extra="first-selected-redactor")
        self.read(initial)
        initial.finish()
        following = self.cache(policy_extra="second-selected-redactor")
        self.assertEqual(self.read(following, redact=lambda value: "[new-policy]")[0], "[new-policy]")
        self.assertEqual(following.stats["source_hits"], 0)

    def test_project_identity_prevents_cross_project_record_replay(self):
        initial = self.warm()
        other = self.root / "other-project"
        other.mkdir()
        (other / "main.py").write_text("different current evidence\n")
        target = parser_cache.Cache(other, directory=self.directory)
        replay = self.directory / target.name
        replay.write_bytes((self.directory / initial.name).read_bytes())
        replay.chmod(0o600)
        target = parser_cache.Cache(other, directory=self.directory)
        self.assertEqual(target.read("main.py", 1000, context._read, lambda value: value)[0],
                         "different current evidence\n")

    def test_warm_sources_still_consume_logical_byte_budget(self):
        self.warm()
        cache = self.cache()
        text, used, reason, _ = self.read(cache, remaining=1)
        self.assertIsNone(text)
        self.assertEqual(used, 0)
        self.assertEqual(reason, "scan byte budget exhausted")
        self.assertEqual(cache.stats["source_hits"], 0)

    def test_source_symlink_and_parent_symlink_cannot_reuse_warm_text(self):
        self.warm()
        (self.project / "main.py").unlink()
        outside = self.root / "outside.py"
        outside.write_text("private outside source")
        (self.project / "main.py").symlink_to(outside)
        cache = self.cache()
        self.assertIsNone(self.read(cache)[0])
        (self.project / "linked").symlink_to(self.root, target_is_directory=True)
        self.assertIsNone(self.read(cache, "linked/outside.py")[0])

    def test_unsafe_cache_directory_and_record_are_preserved(self):
        self.warm()
        self.directory.chmod(0o755)
        cache = self.cache(writable=True)
        self.assertEqual(cache.stats["source_hits"], 0)
        self.assertIsNotNone(self.read(cache)[0])
        cache.finish()
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o755)

    def test_symlinked_record_and_key_are_not_followed_or_replaced(self):
        initial = self.warm()
        outside = self.root / "untouched"
        outside.write_text("outside private data")
        for name in (initial.name, "key"):
            with self.subTest(name=name):
                target = self.directory / name
                saved = target.read_bytes()
                target.unlink()
                target.symlink_to(outside)
                cache = self.cache(writable=True)
                self.assertIsNotNone(self.read(cache)[0])
                cache.finish()
                self.assertTrue(target.is_symlink())
                self.assertEqual(outside.read_text(), "outside private data")
                target.unlink()
                target.write_bytes(saved)
                target.chmod(0o600)

    def test_concurrent_cache_changes_are_not_overwritten(self):
        initial = self.warm()
        following = self.cache(writable=True)
        following.put("facts", "new", ["new fact"])
        record = self.directory / initial.name
        record.write_text("concurrent cache replacement")
        following.finish()
        self.assertEqual(record.read_text(), "concurrent cache replacement")
        self.assertEqual(following.stats["writes"], 0)
        self.assertEqual(following.stats["write_failures"], 1)

    def test_failed_first_save_reports_directory_and_key_mutations(self):
        cache = self.cache(writable=True)
        cache.put("facts", "new", ["new fact"])
        with mock.patch.object(cache, "_write_private", side_effect=OSError("save failed")):
            cache.finish()
        self.assertTrue(self.directory.exists())
        self.assertTrue((self.directory / "key").exists())
        self.assertEqual(cache.stats["writes"], 1)
        self.assertEqual(cache.stats["records_saved"], 0)
        self.assertEqual(cache.stats["write_failures"], 1)

    def test_private_directory_key_and_record_modes(self):
        cache = self.warm()
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.directory / "key").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.directory / cache.name).stat().st_mode & 0o777, 0o600)

    def test_cache_cannot_be_placed_inside_project(self):
        destination = self.project / ".cache"
        cache = parser_cache.Cache(self.project, writable=True, directory=destination)
        self.assertIsNotNone(self.read(cache)[0])
        cache.finish()
        self.assertFalse(destination.exists())

    def test_default_home_alias_is_resolved_but_cache_directory_symlinks_are_refused(self):
        actual_home = self.root / "actual-home"
        actual_home.mkdir()
        alias = self.root / "home-alias"
        alias.symlink_to(actual_home, target_is_directory=True)
        with mock.patch.object(parser_cache.Path, "home", return_value=alias):
            first = parser_cache.Cache(self.project, writable=True)
            self.read(first)
            first.finish()
            following = parser_cache.Cache(self.project)
            self.assertEqual(following.directory, actual_home / ".cache/agent-dispatcher/parser-v1")
            self.read(following)
            self.assertEqual(following.stats["source_hits"], 1)
            self.assertTrue(following.stats["cache_available"])
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        target = actual_home / ".cache/agent-dispatcher/parser-v1"
        import shutil
        shutil.rmtree(target)
        target.symlink_to(elsewhere, target_is_directory=True)
        with mock.patch.object(parser_cache.Path, "home", return_value=alias):
            refused = parser_cache.Cache(self.project, writable=True)
            self.assertFalse(refused.stats["cache_available"])
            self.read(refused)
            refused.finish()
        self.assertFalse(list(elsewhere.iterdir()))

    def test_store_redacted_source_only_with_original_hash(self):
        original = "password = 'private-token-value'\n"
        self.write("main.py", original)
        cache = self.cache(writable=True)
        text, _, _, sha = self.read(cache, redact=lambda value: value.replace("private-token-value", "[redacted]"))
        cache.parse("main.py", text)
        cache.finish()
        self.assertEqual(sha, hashlib.sha256(original.encode()).hexdigest())
        raw = (self.directory / cache.name).read_text()
        self.assertNotIn("private-token-value", raw)
        self.assertIn("[redacted]", raw)

    def test_invalid_utf8_sources_are_not_cached(self):
        (self.project / "main.py").write_bytes(b"invalid\xff")
        cache = self.cache(writable=True)
        text, used, reason, sha = self.read(cache)
        self.assertEqual((text, used, sha), (None, 8, None))
        self.assertIsNotNone(reason)
        cache.finish()
        self.assertFalse(self.directory.exists())

    def test_binary_verdicts_cost_no_read_when_warm_and_a_changed_binary_is_checked_again(self):
        (self.project / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + b"\x01" * 4000)  # Small, NUL in the sniff.
        (self.project / "late.bin").write_bytes(b"x" * (2 * parser_cache.SNIFF_BYTES) + b"\0")  # Small, NUL past it.
        (self.project / "blob.bin").write_bytes(b"\0" * (300 * 1024))
        (self.project / "big.txt").write_text("x\n" * (200 * 1024))
        paths = ["main.py", "icon.png", "late.bin", "blob.bin", "big.txt"]
        uncached = {path: self.read(self.cache(enabled=False), path)[1:3] for path in paths}  # context._read
        self.assertEqual(uncached["icon.png"], (0, "binary file withheld"))  # Sniffed, not read whole, never charged.
        self.assertEqual(uncached["late.bin"], (2 * parser_cache.SNIFF_BYTES + 1, "binary file withheld"))
        cold = self.cache(writable=True)
        self.assertEqual({path: self.read(cold, path)[1:3] for path in paths}, uncached)  # Same verdicts and charges.
        self.assertEqual(cold.stats["source_misses"], 5)
        small = sum((self.project / path).stat().st_size for path in ("main.py", "icon.png", "late.bin"))
        self.assertEqual(cold.stats["source_bytes_read"], small + 2 * parser_cache.SNIFF_BYTES)  # Large files: sniffs only.
        cold.finish()
        self.assertNotIn("IHDR", (self.directory / cold.name).read_text())  # Verdicts only; binary bytes are never kept.
        warm = self.cache()
        with mock.patch.object(parser_cache.os, "read", side_effect=AssertionError("source reread")):
            self.assertEqual({path: self.read(warm, path)[1:3] for path in paths}, uncached)
        self.assertEqual([warm.stats[key] for key in ("source_hits", "source_misses", "source_bytes_read")], [5, 0, 0])
        (self.project / "icon.png").write_text("now text\n")
        changed = self.cache()
        self.assertEqual(self.read(changed, "icon.png")[:3], ("now text\n", 9, None))  # Its old verdict is not served.
        self.assertEqual([changed.stats[key] for key in ("source_hits", "source_misses")], [0, 1])

    def test_source_changing_during_read_is_withheld(self):
        cache = self.cache()
        actual_read = parser_cache.os.read
        changed = False
        def changing_read(descriptor, length):
            nonlocal changed
            result = actual_read(descriptor, length)
            if not changed:
                changed = True
                self.write("main.py", "changed current source\n")
            return result
        with mock.patch.object(parser_cache.os, "read", side_effect=changing_read):
            text, _, reason, _ = self.read(cache)
        self.assertIsNone(text)
        self.assertIn("changed", reason)

    def test_oversized_items_and_non_json_values_are_not_stored(self):
        cache = self.cache(writable=True)
        cache.put("facts", "object", object())
        with mock.patch.object(parser_cache, "MAX_ITEM_BYTES", 5):
            cache.put("facts", "large", "too many bytes")
        self.assertIsNone(cache.get("facts", "object"))
        self.assertIsNone(cache.get("facts", "large"))
        cache.finish()
        self.assertFalse(self.directory.exists())


if __name__ == "__main__":
    unittest.main()
