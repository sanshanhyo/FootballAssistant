'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const workflow = () => fs.readFileSync(path.resolve(__dirname, '../../../.github/workflows/desktop.yml'), 'utf8').replace(/\r\n/g, '\n');
test('Windows distribution builds and audits the reader before uploading a Setup', () => {
  const source = workflow();
  const build = source.indexOf('python scripts/build_windows_reader.py\n');
  const pack = source.indexOf('      - name: Package desktop\n');
  const audit = source.indexOf('python scripts/build_windows_reader.py --verify --output apps/companion/dist/win-unpacked/resources/reader-windows-x64');
  const upload = source.indexOf('      - name: Upload Windows installer separately');
  assert.ok(build > 0 && build < pack && pack < audit && audit < upload);
  assert.match(source, /\$reader --self-test/);
  assert.match(source, /\$probe\.status -ne 'offline_self_test'/);
  assert.match(source, /\$probe\.synthetic -ne \$true/);
  assert.doesNotMatch(source.slice(build, audit), /continue-on-error/);
});
test('reader build bundles runtime without shipping developer/game directories', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../../../scripts/build_windows_reader.py'), 'utf8');
  assert.match(source, /"--self-contained", "true"/);
  assert.match(source, /"PublishSingleFile=false"|"-p:PublishSingleFile=false"/);
  assert.match(source, /"THIRD-PARTY-NOTICES.TXT"/);
  assert.doesNotMatch(source, /copytree\(.*(?:local-game|local-data)/);
});
