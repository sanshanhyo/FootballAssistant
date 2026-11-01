"""Build a stdlib-only review bundle; no downloads, credentials or execution."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FILES = ('windows_capture_files.py', 'windows_finite_files.py', 'windows_acceptance_security.py', 'windows_acceptance_launcher.py')

def build(destination):
    destination = Path(destination)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('football_assistant_data/__init__.py', '')
        for name in FILES:
            archive.write(ROOT/'modules/data-core/src/football_assistant_data'/name, 'football_assistant_data/'+name)
        archive.writestr('run_acceptance.py', 'from pathlib import Path\nimport sys\nsys.path.insert(0, str(Path(__file__).resolve().parent))\nfrom football_assistant_data.windows_acceptance_launcher import main\nraise SystemExit(main())\n')
        archive.write(Path(__file__).with_name('README.md'), 'README.md')
    print(json.dumps(dict(bytes=destination.stat().st_size, sha256=hashlib.sha256(destination.read_bytes()).hexdigest())))

if __name__ == '__main__':
    build(sys.argv[1])
