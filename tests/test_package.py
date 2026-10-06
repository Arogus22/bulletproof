#!/usr/bin/env python3
"""Verify that a distributable contains only the public package and valid hashes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('packager', ROOT/'scripts/package.py')
package = importlib.util.module_from_spec(spec); spec.loader.exec_module(package)


class PackagingTests(unittest.TestCase):
    def test_clean_package(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'package with spaces'
            hashes = package.build(target)
            for name in ('.codex-plugin/plugin.json','.agents/plugins/marketplace.json',
                         '.claude-plugin/plugin.json','hooks/codex.json','hooks/hooks.json',
                         'scripts/approval-server.py','codex-skills/testar/SKILL.md','commands/testar.md'):
                self.assertIn(name,hashes)
            for name,digest in hashes.items():
                self.assertEqual(hashlib.sha256((target/name).read_bytes()).hexdigest(),digest)
                self.assertFalse(set(Path(name).parts) & {'.migrar-projeto','.git','__pycache__'})
            self.assertEqual(json.loads((target/'PACKAGE-MANIFEST.json').read_text()),hashes)
            with self.assertRaises(ValueError):package.build(target)


if __name__=='__main__':unittest.main()
