'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.join(__dirname, '../src/vendor/notices/lazy-val-1.0.5');

test('lazy-val provenance preserves fixed package declaration without claiming full license text', () => {
  const source = fs.readFileSync(path.join(root, 'upstream-package.json'));
  const pkg = JSON.parse(source);
  const record = JSON.parse(fs.readFileSync(path.join(root, 'provenance.json'), 'utf8'));
  assert.equal(pkg.name, 'lazy-val');
  assert.equal(pkg.version, '1.0.5');
  assert.equal(pkg.license, 'MIT');
  assert.equal(pkg.author, 'Vladimir Krivosheev');
  assert.equal(crypto.createHash('sha256').update(source).digest('hex'), record.package_metadata_sha256);
  assert.equal(record.upstream_license_text_verified, false);
  assert.equal(record.status, 'upstream_declared_MIT_full_text_not_supplied');
  assert.equal(record.git_head, 'b69ad4119f1b19bdab13c61ee2fcc88d46b89071');
  assert.equal(record.tarball_sha256, '7d8602ad98db3d19fbd5b46fbf3831dd996197a013ef1ff7badc205e41435372');
});

test('lazy-val notice is explicitly a provenance note, not an invented upstream license', () => {
  const notice = fs.readFileSync(path.join(root, 'NOTICE.md'), 'utf8');
  assert.match(notice, /not an upstream LICENSE file/);
  assert.match(notice, /Open distribution-review item/);
  assert.match(notice, /does not invent a copyright/);
  assert.doesNotMatch(notice, /Copyright \(c\) \d{4}/);
});

test('Git preserves upstream evidence bytes under Windows CRLF checkout', () => {
  const attributes = fs.readFileSync(path.join(__dirname, '../../..', '.gitattributes'), 'utf8');
  assert.match(attributes, /^\/apps\/companion\/src\/vendor\/notices\/lazy-val-1\.0\.5\/upstream-package\.json -text$/m);
  for (const file of ['LICENSE.txt', 'AUTHORS.md', 'ACKNOWLEDGEMENTS.md', 'README.md']) {
    assert.ok(attributes.includes(`/packaging/licenses/openssl-3.0.16/${file} -text`));
  }
});
