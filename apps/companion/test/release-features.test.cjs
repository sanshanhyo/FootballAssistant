'use strict';
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { ALPHA_TTS_ENABLED, speakWhenEnabled } = require('../src/release-features.cjs');
test('Alpha 0.0.1 rejects speech before invoking the provider', () => {
  let called = false;
  assert.equal(ALPHA_TTS_ENABLED, false);
  assert.throws(() => speakWhenEnabled(() => { called = true; }), /TTS is disabled/);
  assert.equal(called, false);
});

test('desktop artifact excludes local runtime, credentials, captures, logs and saves', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  assert.equal(manifest.version, '0.0.1-alpha.1');
  const files = manifest.build.files;
  assert.deepEqual(files.filter(item => !item.startsWith('!')), ['src/**/*', 'THIRD_PARTY.md', 'package.json']);
  for (const excluded of ['!**/.env*', '!**/runtime.json', '!**/local-data/**', '!**/local-game/**', '!**/*.db', '!**/*.sqlite*', '!**/*.log', '!**/*.fm', '!**/*.fms']) assert.ok(files.includes(excluded));
  assert.equal(manifest.build.extraResources.length, 1);
  const backend = manifest.build.extraResources[0];
  assert.equal(backend.from, '../../build/desktop-backend/football-assistant-backend');
  assert.equal(backend.to, 'backend');
  for (const excluded of ['!**/.env*', '!**/runtime.json', '!**/credentials*.json', '!**/local-game/**', '!**/*.fm']) assert.ok(backend.filter.includes(excluded));
  assert.deepEqual(manifest.build.win.target.map(target => target.target), ['nsis', 'portable']);
  assert.equal(manifest.build.nsis.deleteAppDataOnUninstall, false);
  assert.equal(manifest.build.nsis.perMachine, false);
  assert.equal(manifest.build.nsis.allowElevation, false);
  assert.notEqual(manifest.build.nsis.artifactName, manifest.build.portable.artifactName);
  assert.equal(manifest.build.extraFiles, undefined);
  assert.match(manifest.scripts['pack:win'], /--publish never/);
  assert.match(manifest.scripts['pack:mac'], /--publish never/);
  assert.equal(manifest.build.publish.repo, 'FootballAssistant');
});
