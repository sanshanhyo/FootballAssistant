"""User-owned shadow deployment. Never downloads payloads or starts/stops a game."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import uuid

GAME_VERSION = "27.0.0.2486716"
GAME_SHA = "1c478ecc9a3d984c649a22289ce74cf403d86af7629318177fdc80c7f252c1e5"

class SetupError(ValueError):
    pass

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def ordinary(path, limit=None):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise SetupError('unsafe_file')
    if limit and path.stat().st_size > limit:
        raise SetupError('file_too_large')
    return path

def private_path(path):
    if not path.is_absolute() or path != path.resolve():
        raise SetupError('unsafe_path')
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise SetupError('unsafe_path')
    return path

def read_json(path):
    return json.loads(ordinary(path, 262144).read_text(encoding='utf-8'))

def write_json(path, value):
    private_path(path.parent)
    if path.exists(): ordinary(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def running_game():
    # A failed process check is not evidence that it is safe to deploy/rollback.
    result = subprocess.run(['/bin/ps', '-A', '-o', 'comm='], capture_output=True, text=True, check=True, timeout=5)
    return any(Path(line.strip()).name.lower() in {'fm', 'fm27', 'football manager 27'} for line in result.stdout.splitlines())

def inspect_game(game):
    private_path(game)
    if game.suffix.lower() != '.app': raise SetupError('unsupported_game')
    info = plistlib.loads(ordinary(game / 'Contents/Info.plist', 1048576).read_bytes())
    executable_name = info.get('CFBundleExecutable')
    if not isinstance(executable_name, str) or Path(executable_name).name != executable_name:
        raise SetupError('unsupported_game')
    if info.get('CFBundleIdentifier') != 'com.SportsInteractive.FootballManager27' or info.get('CFBundleShortVersionString') != GAME_VERSION:
        raise SetupError('unsupported_game_version')
    executable = ordinary(game / 'Contents/MacOS' / executable_name)
    if digest(executable) != GAME_SHA: raise SetupError('unsupported_game_fingerprint')
    return {'gamePath': str(game), 'gameVersion': GAME_VERSION, 'architecture': 'arm64', 'gameSha256': GAME_SHA, 'executableBytes': executable.stat().st_size}

def validate_payload(payload):
    private_path(payload)
    manifest = read_json(payload / 'payload.json')
    if manifest.get('schema') != 1 or manifest.get('target') != 'darwin-arm64' or manifest.get('reviewed') is not True:
        raise SetupError('payload_unreviewed')
    files = manifest.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 2000: raise SetupError('payload_invalid')
    for relative, expected in files.items():
        rel = Path(relative)
        if rel.is_absolute() or '..' in rel.parts or not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected): raise SetupError('payload_invalid')
        file = ordinary(payload / rel)
        if file.resolve() != file or not file.is_relative_to(payload) or digest(file) != expected: raise SetupError('payload_hash_mismatch')
    # The existing preparer copies every file in these directories; extras cannot sneak in.
    folders = ['runtime'] if manifest.get('entryMode') == 'direct' else ['compat/dist/bepinex-core', 'compat/dist/dotnet-extras', 'runtime']
    for folder in folders:
        root = private_path(payload / folder)
        if not root.is_dir(): raise SetupError('payload_incomplete')
        for file in root.iterdir():
            ordinary(file)
            if str(file.relative_to(payload)) not in files: raise SetupError('payload_unlisted_file')
    for required in ['libdoorstop.dylib', 'FootballAssistant.GameBridge.dll', 'runtime/libcoreclr.dylib']:
        if required not in files: raise SetupError('payload_incomplete')
    return digest(payload / 'payload.json')

def prepare(game, destination, payload, apply):
    scripts = Path(sys._MEIPASS) / 'game-bridge-scripts' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[4] / 'modules/game-bridge/scripts'
    spec = importlib.util.spec_from_file_location('fa_prepare_' + uuid.uuid4().hex, scripts / 'prepare_isolated.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    args = ['--game-path', str(game), '--private-root', str(destination), '--plugin-path', str(payload / 'FootballAssistant.GameBridge.dll'), '--compat-dir', str(payload / 'compat'), '--runtime-dir', str(payload / 'runtime'), '--doorstop-path', str(payload / 'libdoorstop.dylib')]
    if read_json(payload / 'payload.json').get('entryMode') == 'direct':
        offset = args.index('--compat-dir'); del args[offset:offset+2]; args += ['--direct-host']
    if apply: args += ['--apply', '--allow-shadow-signing']
    with contextlib.redirect_stdout(io.StringIO()): module.main(args)

class BridgeSetup:
    def __init__(self, data_dir, payload_dir, *, system=None, architecture=None):
        self.root = private_path(Path(data_dir).absolute()) / 'bridge'
        self.payload = Path(payload_dir).absolute()
        self.system = system or sys.platform
        self.architecture = architecture or platform.machine().lower()
    def supported(self):
        if self.system != 'darwin': raise SetupError('unsupported_platform')
        if self.architecture not in {'arm64', 'aarch64'}: raise SetupError('unsupported_architecture')
    def initialize(self):
        private_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for folder in ['plans', 'instances']:
            private_path(self.root / folder).mkdir(exist_ok=True, mode=0o700)
    def inspect(self):
        self.supported()
        candidate = Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app'
        result = {'state': 'not_configured', 'canEnable': False, 'payloadReady': False, 'canRollback': False, 'dataConnected': False, 'candidates': [str(candidate)] if candidate.is_dir() else []}
        try:
            validate_payload(self.payload); result['payloadReady'] = True
        except (OSError, ValueError): result['state'] = 'payload_unavailable'
        if (self.root / 'deployment.json').exists():
            receipt = self.receipt()
            result.update(state='disabled' if receipt.get('disabled') else 'deployed', privateRoot=receipt['privateRoot'], canRollback=True)
        return result
    def space(self, facts):
        copies = sum(file.stat().st_size for file in self.payload.rglob('*') if file.is_file() and not file.is_symlink() and file.suffix in {'.dll', '.dylib'})
        required = int((copies + facts.get('executableBytes', 0)) * 1.2) + 64 * 1024 * 1024
        available = shutil.disk_usage(self.root).free
        if available < required: raise SetupError('insufficient_disk_space')
        return {'requiredBytes': required, 'availableBytes': available}
    def plan(self, game_path):
        self.supported(); self.initialize()
        game = Path(game_path).expanduser().absolute()
        facts = inspect_game(game)
        payload_sha = validate_payload(self.payload)
        if running_game(): raise SetupError('game_running')
        if (self.root / 'deployment.json').exists() and not self.receipt().get('disabled'): raise SetupError('already_deployed')
        plan_id = uuid.uuid4().hex
        destination = self.root / 'instances' / plan_id
        prepare(game, destination, self.payload, False)
        space = self.space(facts)
        plan = {**facts, 'diskSpace': space, 'planId': plan_id, 'privateRoot': str(destination), 'payloadSha256': payload_sha, 'createdAt': time.time(), 'requiresShadowSigning': True, 'requiresJit': True, 'canEnable': True, 'state': 'planned', 'dataConnected': False, 'changes': ['仅创建用户目录中的独立游戏可执行文件副本', '只对副本进行 ad-hoc 签名并启用 JIT entitlement', '原 Steam 文件、启动参数及系统安全设置保持不变', '不会启动、终止或重启游戏']}
        write_json(self.root / 'plans' / (plan_id + '.json'), plan)
        return plan
    def deploy(self, plan_id, consent):
        self.supported(); self.initialize()
        if consent is not True: raise SetupError('consent_required')
        if not re.fullmatch('[a-f0-9]{32}', plan_id or ''): raise SetupError('invalid_plan')
        plan = read_json(self.root / 'plans' / (plan_id + '.json'))
        destination = self.root / 'instances' / plan_id
        if plan.get('privateRoot') != str(destination) or plan.get('planId') != plan_id or not 0 <= time.time()-plan.get('createdAt', 0) <= 600: raise SetupError('expired_plan')
        if ((self.root / 'deployment.json').exists() and not self.receipt().get('disabled')) or destination.exists(): raise SetupError('already_deployed')
        if running_game(): raise SetupError('game_running')
        game = Path(plan['gamePath']); self.space(inspect_game(game))
        if validate_payload(self.payload) != plan['payloadSha256']: raise SetupError('payload_changed')
        try:
            prepare(game, destination, self.payload, True)
            inspect_game(game)  # Recheck original source after copying/signing shadow.
            receipt = {'schema': 1, 'planId': plan_id, 'privateRoot': str(destination), 'gamePath': str(game), 'createdAt': time.time()}
            write_json(self.root / 'deployment.json', receipt)
        except Exception:
            # Only our fresh unique instance; shutil does not traverse directory symlinks.
            if destination.is_dir() and not destination.is_symlink(): shutil.rmtree(destination)
            raise
        return {**receipt, 'state': 'deployed', 'dataConnected': False, 'canEnable': False, 'message': '私有副本已准备，游戏未启动；尚未连接游戏数据。'}
    def receipt(self):
        receipt = read_json(self.root / 'deployment.json')
        plan_id = receipt.get('planId', '')
        if not isinstance(plan_id, str) or not re.fullmatch('[a-f0-9]{32}', plan_id): raise SetupError('invalid_receipt')
        destination = self.root / 'instances' / plan_id
        if receipt.get('privateRoot') != str(destination): raise SetupError('invalid_receipt')
        private_path(destination)
        if not destination.is_dir(): raise SetupError('invalid_receipt')
        return receipt
    def rollback(self):
        self.supported(); self.initialize()
        if running_game(): raise SetupError('game_running')
        receipt = self.receipt()
        destination = Path(receipt['privateRoot'])
        # Idempotent receipt retained for retry if desktop config persistence fails.
        write_json(self.root / 'deployment.json', {**receipt, 'disabled': True})
        return {'state': 'disabled', 'privateRoot': '', 'preservedRoot': str(destination), 'dataConnected': False, 'message': '桥接已停用，原版未修改；私有副本及日志保留。'}

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'plan', 'deploy', 'rollback'])
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--payload-dir', required=True)
    parser.add_argument('--game-path')
    parser.add_argument('--plan-id')
    parser.add_argument('--consent-shadow-signing-and-jit', action='store_true')
    args = parser.parse_args(argv)
    try:
        setup = BridgeSetup(args.data_dir, args.payload_dir)
        if args.action == 'plan': result = setup.plan(args.game_path or '')
        elif args.action == 'deploy': result = setup.deploy(args.plan_id, args.consent_shadow_signing_and_jit)
        else: result = getattr(setup, args.action)()
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        error = sys.exc_info()[1]
        code = str(error) if isinstance(error, SetupError) else 'deployment_check_failed'
        print(json.dumps({'state': code, 'canEnable': False, 'dataConnected': False, 'message': '桥接未启用：' + code}, ensure_ascii=False)); return 0
