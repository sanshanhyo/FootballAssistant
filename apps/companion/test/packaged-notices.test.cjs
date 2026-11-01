'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { auditArchive } = require('../packaging/audit-notices.cjs');
function fixture() {
  const files = new Map();
  for (const name of ['THIRD_PARTY.md', 'src/vendor/dsh-pet-LICENSE.txt', 'src/assets/fonts/851GBaiMarker-LICENSE.txt', 'src/assets/fonts/851-original-author-terms.html', ...['NOTICE.md', 'provenance.json', 'upstream-package.json'].map(n => 'src/vendor/notices/lazy-val-1.0.5/' + n)]) files.set(name, fs.readFileSync(path.join(__dirname, '..', name)));
  files.set('node_modules/lazy-val/package.json', Buffer.from('{"name":"lazy-val","version":"1.0.5","license":"MIT"}'));
  return files;
}
const audit = files => auditArchive([...files.keys()], file => files.get(file));
test('declared-only upstream license remains an explicit open issue, never legal completion', () => {
  const report = audit(fixture());
  assert.equal(report.legal_review_complete, false);
  assert.equal(report.packages[0].status, 'declared_license_only_open_issue');
  assert.equal(report.open_issues.length, 2);
});
test('missing notices and mutated provenance fail the package audit', () => {
  const files = fixture(); files.delete('src/vendor/dsh-pet-LICENSE.txt');
  assert.throws(() => audit(files), /Missing bundled notice/);
  const changed = fixture(); changed.set('src/vendor/notices/lazy-val-1.0.5/upstream-package.json', Buffer.from('{}'));
  assert.throws(() => audit(changed), /Invalid declared-only/);
});
test('new unlicensed runtime dependency cannot use lazy-val exception', () => {
  const files = fixture(); files.set('node_modules/new-package/package.json', Buffer.from('{"name":"new-package","version":"1"}'));
  assert.throws(() => audit(files), /No license text/);
});

test('nested runtime packages are audited and changed lazy-val declaration is rejected', () => {
  const files = fixture(); files.set('node_modules/a/node_modules/@scope/b/package.json', Buffer.from('{"name":"@scope/b","version":"1"}'));
  assert.throws(() => audit(files), /No license text: @scope\/b/);
  const changed = fixture(); changed.set('node_modules/lazy-val/package.json', Buffer.from('{"name":"lazy-val","version":"1.0.5","license":"Other"}'));
  assert.throws(() => audit(changed), /Invalid declared-only/);
});

test('actual OpenSSL pair requires version-matched notices and records post-sign hashes', () => {
  const { auditOpenSsl } = require('../packaging/audit-notices.cjs');
  const crypto = Buffer.from('OpenSSL 3.0.16 11 Feb 2025\0'); const ssl = Buffer.from('signed SSL bytes');
  assert.deepEqual(auditOpenSsl({ components: [] }, null, null), []);
  assert.throws(() => auditOpenSsl({ components: [] }, crypto, ssl), /notices missing/);
  const manifest = { components: [{ name: 'OpenSSL', version: '3.0.16', binary_evidence: [{ sha256: 'different-pre-sign-hash' }] }] };
  assert.equal(auditOpenSsl(manifest, crypto, ssl).length, 2);
  assert.equal(auditOpenSsl(manifest, crypto, ssl)[0].hash_stage, 'packaged-after-app-signing');
  assert.throws(() => auditOpenSsl(manifest, Buffer.from('OpenSSL 3.0.17 new\0'), ssl), /Unreviewed/);
  assert.throws(() => auditOpenSsl(manifest, crypto, null), /Incomplete/);
});

test('asar Windows path separators use the same strict archive inventory', () => {
  const files = fixture();
  const report = auditArchive([...files.keys()].map(file => '\\' + file.replaceAll('/', '\\')), file => files.get(file));
  assert.equal(report.packages.length, 1);
  assert.equal(report.packages[0].status, 'declared_license_only_open_issue');
});

test('asar extraction receives native paths after cross-platform inventory normalization', () => {
  const { nativeArchivePath } = require('../packaging/audit-notices.cjs');
  assert.equal(nativeArchivePath('node_modules/a/LICENSE', path.win32), 'node_modules\\a\\LICENSE');
  assert.equal(nativeArchivePath('node_modules/a/LICENSE', path.posix), 'node_modules/a/LICENSE');
});
