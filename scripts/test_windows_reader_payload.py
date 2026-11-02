"""Offline packaging regression: fixtures are not game acceptance."""
import json
from pathlib import Path
import tempfile
import unittest
from build_windows_reader import finalize, verify

class ReaderPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.output = root / 'out'; self.output.mkdir()
        self.runtime = root / '10.0.0'; self.runtime.mkdir()
        for name in ['OffseasonReaderCli.exe', 'OffseasonReaderCli.dll', 'FootballAssistant.OffseasonReader.dll', 'coreclr.dll', 'hostfxr.dll', 'hostpolicy.dll']:
            (self.output/name).write_bytes(b'MZ' + b'fixture-not-real-binary')
        for name in ['LICENSE.TXT', 'THIRD-PARTY-NOTICES.TXT']:
            (self.runtime/name).write_text('fixture license ' * 20)
    def prepare(self):
        return finalize(self.output, self.runtime, 'a'*40)
    def test_complete_inventory_and_identity(self):
        self.prepare(); m=verify(self.output)
        self.assertEqual(m['protocol'], 'fa-offseason/0.1')
        self.assertEqual(m['realGameAcceptance'], 'pending')
        self.assertFalse(m['gameFilesIncluded'])
    def test_missing_runtime_fails(self):
        (self.output/'coreclr.dll').unlink()
        with self.assertRaises(ValueError): self.prepare()
    def test_missing_license_fails(self):
        (self.runtime/'LICENSE.TXT').unlink()
        with self.assertRaises(ValueError): self.prepare()
    def test_changed_binary_fails(self):
        self.prepare(); (self.output/'OffseasonReaderCli.exe').write_bytes(b'MZtampered')
        with self.assertRaises(ValueError): verify(self.output)
    def test_unlisted_file_fails(self):
        self.prepare(); (self.output/'extra.dll').write_bytes(b'MZunknown')
        with self.assertRaises(ValueError): verify(self.output)
    def test_missing_entry_even_if_inventory_rewritten_fails(self):
        m=self.prepare(); (self.output/'OffseasonReaderCli.exe').unlink(); del m['files']['OffseasonReaderCli.exe']
        (self.output/'manifest.json').write_text(json.dumps(m))
        with self.assertRaises(ValueError): verify(self.output)

if __name__ == '__main__': unittest.main()
