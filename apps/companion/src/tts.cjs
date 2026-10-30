'use strict';
const { spawn } = require('node:child_process');

const WINDOWS_SCRIPT = [
  'Add-Type -AssemblyName System.Speech;',
  '[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false);',
  '$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new();',
  '$voice = $speaker.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like "zh-*" } | Select-Object -First 1;',
  'if ($voice) { $speaker.SelectVoice($voice.VoiceInfo.Name); }',
  '$speaker.Speak([Console]::In.ReadToEnd());',
  '$speaker.Dispose();',
].join(' ');

function speechCommand(platform) {
  if (platform === 'darwin') return { file: '/usr/bin/say', args: ['-v', process.env.FOOTBALL_ASSISTANT_TTS_VOICE || 'Tingting', '-r', '185'] };
  if (platform === 'win32') return {
    file: 'powershell.exe',
    args: ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(WINDOWS_SCRIPT, 'utf16le').toString('base64')],
  };
  throw new Error('当前平台暂未接入系统朗读。');
}

function createSpeech(onState, options = {}) {
  let active = null;
  function stop() {
    if (active) {
      const child = active;
      active = null;
      child.kill();
    }
    onState({ state: 'stopped' });
  }
  function speak(text) {
    if (typeof text !== 'string' || !text.trim() || text.length > 12_000) throw new Error('朗读文本为空或过长。');
    stop();
    const command = speechCommand(options.platform || process.platform);
    const child = (options.spawn || spawn)(command.file, command.args, { windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'] });
    active = child;
    let errorText = '';
    child.stderr.on('data', chunk => { errorText = (errorText + chunk.toString()).slice(-500); });
    child.stdin.on('error', () => {});
    child.once('error', error => {
      if (active !== child) return;
      active = null;
      onState({ state: 'error', message: `系统朗读启动失败：${error.message}` });
    });
    child.once('exit', code => {
      if (active !== child) return;
      active = null;
      onState(code === 0 ? { state: 'finished' } : { state: 'error', message: errorText.trim() || `系统朗读退出（${code}）。` });
    });
    child.stdin.end(text, 'utf8');
    onState({ state: 'speaking' });
    return { state: 'speaking' };
  }
  return { speak, stop };
}

module.exports = { createSpeech, speechCommand };
