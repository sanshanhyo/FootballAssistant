'use strict';
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

// Bundled, immutable build assets. No PATH lookup, shell, model download or audio upload.
function createLocalWhisper(options = {}) {
  const platform = options.platform || process.platform;
  const root = options.assetRoot || path.join(process.resourcesPath || path.resolve(__dirname, '..'), 'local-stt');
  const executable = path.join(root, platform === 'win32' ? 'whisper-cli.exe' : 'whisper-cli');
  const model = path.join(root, 'ggml-tiny-q5_1.bin');
  const spawnImpl = options.spawn || spawn;
  function capability() {
    let available = false;
    try {
      available = fs.statSync(executable).isFile() && fs.statSync(model).size === 32152673;
      fs.accessSync(executable, platform === 'win32' ? fs.constants.F_OK : fs.constants.X_OK);
    } catch { available = false; }
    return { id: 'local-whisper', label: '本地 Whisper Tiny · 31 MB', available, configured: available,
      synthetic: false, local: true, model: 'tiny-q5_1', modelBytes: 32152673,
      reason: available ? null : '本地语音组件未安装，请使用包含 Whisper 的新版安装包。' };
  }
  async function transcribe(bytes, language, signal) {
    if (!capability().available) throw new Error('Local Whisper assets are missing');
    // The renderer decodes compressed recordings locally to mono 16 kHz PCM WAV.
    const audio = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (audio.length < 46 || audio.toString('ascii', 0, 4) !== 'RIFF' || audio.toString('ascii', 8, 12) !== 'WAVE'
        || audio.toString('ascii', 12, 16) !== 'fmt ' || audio.readUInt32LE(16) !== 16
        || audio.readUInt16LE(20) !== 1 || audio.readUInt16LE(22) !== 1 || audio.readUInt32LE(24) !== 16000
        || audio.readUInt16LE(34) !== 16 || audio.toString('ascii', 36, 40) !== 'data'
        || audio.readUInt32LE(40) !== audio.length - 44 || audio.length > 44 + 16000 * 2 * 65) {
      throw new Error('Expected bounded mono 16 kHz PCM WAV');
    }
    if (signal.aborted) throw signal.reason;
    const directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'football-local-stt-'));
    const input = path.join(directory, 'recording.wav');
    const output = path.join(directory, 'transcript');
    try {
      await fsp.writeFile(input, audio, { mode: 0o600 });
      if (signal.aborted) throw signal.reason;
      await new Promise((resolve, reject) => {
        const child = spawnImpl(executable, ['-m', model, '-f', input, '-l', language?.split('-')[0] || 'auto',
          '-t', String(Math.max(1, Math.min(4, os.availableParallelism?.() || os.cpus().length))),
          '-ng', '-nt', '-otxt', '-of', output], { shell: false, windowsHide: true, stdio: 'ignore' });
        let settled = false;
        const finish = error => {
          if (settled) return;
          settled = true;
          signal.removeEventListener('abort', abort);
          if (error) reject(error); else resolve();
        };
        // Wait for process close before removing its private temporary directory.
        const abort = () => { child.kill('SIGKILL'); };
        signal.addEventListener('abort', abort, { once: true });
        child.once('error', error => finish(error));
        child.once('close', code => finish(signal.aborted ? signal.reason : code === 0 ? null : new Error('Local transcription failed')));
        if (signal.aborted) abort();
      });
      if (signal.aborted) throw signal.reason;
      const result = `${output}.txt`;
      if ((await fsp.stat(result)).size > 64 * 1024) throw new Error('Local transcript exceeded limit');
      const text = (await fsp.readFile(result, 'utf8')).trim();
      if (text.length > 12000) throw new Error('Local transcript exceeded limit');
      return text;
    } finally { await fsp.rm(directory, { recursive: true, force: true }); }
  }
  return { capability, transcribe };
}
module.exports = { createLocalWhisper };
