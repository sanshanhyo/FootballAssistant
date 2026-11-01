"""Build pinned CPU-only whisper.cpp and bundle verified tiny multilingual weights.
Requires Python >=3.12, CMake >=3.21 and a C++ compiler. No runtime download.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

COMMIT = 'a8d002cfd879315632a579e73f0148d06959de36'  # whisper.cpp v1.7.6
SOURCE_SHA256 = '7b17da903114ed45d82f48c030e3be6a5a8a279f884b2f733706dbb4e832fb6b'
MODEL_REV = '5359861c739e955e79d9a303bcbc70fb988958b1'
MODEL_SHA256 = '818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7'
MODEL_BYTES = 32152673
ROOT = Path(__file__).resolve().parent.parent


def download(url, target, expected, max_bytes):
    with urllib.request.urlopen(url, timeout=120) as response, target.open('wb') as output:
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise RuntimeError('Download exceeds declared size limit')
            output.write(chunk)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f'Checksum mismatch: {target.name}')


def main():
    destination = ROOT / 'local-stt'
    with tempfile.TemporaryDirectory(prefix='fa-whisper-build-') as temporary:
        work = Path(temporary)
        archive = work / 'source.tar.gz'
        download(f'https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/{COMMIT}', archive, SOURCE_SHA256, 20 * 1024 * 1024)
        with tarfile.open(archive) as source:
            source.extractall(work, filter='data')
        source = work / f'whisper.cpp-{COMMIT}'
        build = work / 'build'
        # Disable host-specific CPU tuning and GPU dependencies: same artifact runs on older x64 CPUs.
        command = ['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                   '-DBUILD_SHARED_LIBS=OFF', '-DGGML_NATIVE=OFF', '-DGGML_METAL=OFF',
                   '-DGGML_OPENMP=OFF', '-DGGML_BLAS=OFF', '-DGGML_CUDA=OFF',
                   '-DGGML_AVX=OFF', '-DGGML_AVX2=OFF', '-DGGML_FMA=OFF', '-DGGML_F16C=OFF',
                   '-DWHISPER_BUILD_TESTS=OFF', '-DWHISPER_BUILD_SERVER=OFF',
                   '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded']
        subprocess.run(command, check=True)
        subprocess.run(['cmake', '--build', str(build), '--config', 'Release', '--target', 'whisper-cli', '-j', '2'], check=True)
        executable = 'whisper-cli.exe' if sys.platform == 'win32' else 'whisper-cli'
        binary = next(build.rglob(executable))
        staged = work / 'assets'
        staged.mkdir()
        shutil.copy2(binary, staged / executable)
        (staged / executable).chmod(0o755)
        download(f'https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REV}/ggml-tiny-q5_1.bin',
                 staged / 'ggml-tiny-q5_1.bin', MODEL_SHA256, MODEL_BYTES)
        if (staged / 'ggml-tiny-q5_1.bin').stat().st_size != MODEL_BYTES:
            raise RuntimeError('Incorrect model size')
        shutil.copy2(source / 'LICENSE', staged / 'WHISPER-CPP-LICENSE.txt')
        for filename in ['miniaudio.h', 'stb_vorbis.c']:
            content = (source / 'examples' / filename).read_text()
            start = content.rfind('This software is available')
            if start < 0:
                raise RuntimeError(f'Missing retained license: {filename}')
            (staged / f'{filename}-LICENSE.txt').write_text(content[start:])
        model_license = ROOT / 'packaging' / 'WHISPER-MODEL-LICENSE.txt'
        if hashlib.sha256(model_license.read_bytes()).hexdigest() != 'b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d':
            raise RuntimeError('Whisper model license integrity check failed')
        shutil.copy2(model_license, staged / 'WHISPER-MODEL-LICENSE.txt')
        manifest = {'engineCommit': COMMIT, 'modelRevision': MODEL_REV, 'modelSha256': MODEL_SHA256,
                    'modelBytes': MODEL_BYTES, 'cpuOnly': True, 'model': 'tiny-q5_1', 'multilingual': True}
        (staged / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Exercise real inference against upstream's public JFK sample; no microphone or user audio.
        result = work / 'smoke'
        subprocess.run([str(staged / executable), '-m', str(staged / 'ggml-tiny-q5_1.bin'),
                        '-f', str(source / 'samples' / 'jfk.wav'), '-l', 'en', '-ng', '-otxt', '-of', str(result)],
                       check=True, timeout=120)
        transcript = result.with_suffix('.txt').read_text().lower()
        if 'country' not in transcript:
            raise RuntimeError('Real Whisper smoke did not recognize reference audio')
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(staged, destination)
        print(f'Bundled local Whisper assets: {destination}; model {MODEL_BYTES} bytes; real CPU smoke passed')


if __name__ == '__main__':
    main()
