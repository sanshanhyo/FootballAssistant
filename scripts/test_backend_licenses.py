"""Run with python -m unittest discover -s scripts -p 'test_backend_licenses.py'."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from collect_backend_licenses import collect, cpython_framework_metadata, digest, entries, verify


class LicenseInventoryTests(unittest.TestCase):
    def test_nested_analysis_entries(self):
        value = ([('fastapi', '/tmp/fastapi.py', 'PYMODULE')], ('not', 'an', 'entry'))
        self.assertEqual(list(entries(value)), [('fastapi', '/tmp/fastapi.py', 'PYMODULE')])

    def test_valid_and_tampered_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notice = root / 'LICENSE'
            notice.write_text('Example notice', encoding='utf-8')
            manifest = {'components': [{'name': 'example', 'files': [{'path': 'LICENSE', 'sha256': digest(notice)}]}]}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(len(verify(root)['components']), 1)
            notice.write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                verify(root)
            notice.unlink()
            with self.assertRaises(ValueError):
                verify(root)

    def test_missing_notices_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for records in ([], [{'path': '../outside', 'sha256': 'bad'}]):
                (root / 'manifest.json').write_text(json.dumps({'components': [{'name': 'bad', 'files': records}]}))
                with self.assertRaises(ValueError):
                    verify(root)

    def test_unknown_python_and_data_fail_with_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ('PYMODULE', 'PYSOURCE', 'DATA'):
                analysis = root / 'Analysis-00.toc'
                source = root / 'site-packages/missing_record/module.py'
                analysis.write_text(repr([('mystery', str(source), kind)]))
                output = root / kind
                with patch('collect_backend_licenses.metadata.distributions', return_value=[]):
                    with self.assertRaisesRegex(ValueError, 'Unresolved bundled'):
                        collect(analysis, output)
                report = json.loads((output / 'coverage.json').read_text())
                self.assertEqual(report['unresolved'][0]['name'], 'mystery')

    def test_authors_only_is_not_license_even_with_spdx(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'module.py').write_text('pass')
            (root / 'AUTHORS').write_text('Some author')
            analysis = root / 'Analysis-00.toc'
            analysis.write_text(repr([('example', str(root / 'module.py'), 'PYMODULE')]))
            dist = SimpleNamespace(metadata={'Name': 'example', 'License-Expression': 'MIT'},
                                   version='1', files=['module.py', 'AUTHORS'],
                                   locate_file=lambda file: root / file)
            with patch('collect_backend_licenses.metadata.distributions', return_value=[dist]):
                with self.assertRaisesRegex(ValueError, 'No full license text'):
                    collect(analysis, root / 'output')

    def test_stdlib_project_namespace_and_generated_archive_classified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, stdlib = root / 'project', root / 'stdlib'
            project.mkdir(); stdlib.mkdir()
            (project / 'LICENSE').write_text('Project test license')
            (stdlib / 'LICENSE.txt').write_text('Runtime test license')
            analysis = root / 'Analysis-00.toc'
            analysis.write_text(repr([
                ('os', str(stdlib / 'os.py'), 'PYMODULE'),
                ('own', str(project / 'scripts/own.py'), 'PYSOURCE'),
                ('namespace', '-', 'PYMODULE'),
                ('base_library.zip', str(root / 'base_library.zip'), 'DATA'),
            ]))
            with patch('collect_backend_licenses.ROOT', project), \
                 patch('collect_backend_licenses.metadata.distributions', return_value=[]), \
                 patch('collect_backend_licenses.sysconfig.get_path', return_value=str(stdlib)):
                result = collect(analysis, root / 'output')
            report = json.loads((root / 'output/coverage.json').read_text())
            self.assertEqual(report['unresolved'], [])
            self.assertEqual({x['category'] for x in report['entries']}, {
                'cpython-stdlib', 'project', 'namespace-no-file', 'pyinstaller-generated-stdlib-archive'})
            self.assertEqual(len(result['components']), 2)
            (root / 'output/coverage.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'coverage inventory'):
                verify(root / 'output')

    def test_cpython_framework_metadata_exact_interpreter_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / 'Python.framework/Versions/3.12'
            source = prefix / 'Resources/Info.plist'
            source.parent.mkdir(parents=True)
            source.write_text('<plist/>')
            name = 'Python.framework/Versions/3.12/Resources/Info.plist'
            config = {'PYTHONFRAMEWORK': 'Python', 'PYTHONFRAMEWORKPREFIX': str(root)}
            with patch('collect_backend_licenses.sys.platform', 'darwin'), \
                 patch('collect_backend_licenses.sys.base_prefix', str(prefix)), \
                 patch('collect_backend_licenses.sys.version_info', SimpleNamespace(major=3, minor=12)), \
                 patch('collect_backend_licenses.sysconfig.get_config_var', side_effect=config.get):
                self.assertTrue(cpython_framework_metadata(name, source.resolve(), 'DATA'))
                self.assertFalse(cpython_framework_metadata(name.replace('3.12', '3.11'), source.resolve(), 'DATA'))
                self.assertFalse(cpython_framework_metadata(name, source.resolve(), 'PYMODULE'))
                outsider = root / 'unrelated/Info.plist'
                outsider.parent.mkdir(); outsider.write_text('<plist/>')
                self.assertFalse(cpython_framework_metadata(name, outsider.resolve(), 'DATA'))
                self.assertFalse(cpython_framework_metadata('Other.framework/Resources/Info.plist', source.resolve(), 'DATA'))
                source.unlink()
                self.assertFalse(cpython_framework_metadata(name, source.resolve(), 'DATA'))


if __name__ == '__main__':
    unittest.main()
