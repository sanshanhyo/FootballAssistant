'use strict';
// Presence/integrity audit only, not a legal compatibility or source-offer review.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function auditArchive(files, read) {
  const present = new Set(files.map(file => file.replace(/^\//, '')));
  const required = ['THIRD_PARTY.md', 'src/vendor/dsh-pet-LICENSE.txt',
    'src/assets/fonts/851GBaiMarker-LICENSE.txt', 'src/assets/fonts/851-original-author-terms.html'];
  const records = [];
  function record(file) {
    if (!present.has(file)) throw new Error(`Missing bundled notice: ${file}`);
    const bytes = read(file);
    if (!bytes.length) throw new Error(`Empty bundled notice: ${file}`);
    records.push({ path: file, sha256: sha256(bytes) });
    return bytes;
  }
  required.forEach(record);
  const packages = [];
  for (const file of present) {
    if (!/(?:^|\/)node_modules\/(?:@[^/]+\/)?[^/]+\/package\.json$/.test(file)) continue;
    const metadata = JSON.parse(read(file));
    const prefix = file.slice(0, -'package.json'.length);
    const notices = [...present].filter(p => p.startsWith(prefix) && /^(?:licen[cs]e|copying)(?:[.-].*)?$/i.test(p.slice(prefix.length)));
    let status = 'license_text_present';
    if (!notices.length) {
      if (metadata.name !== 'lazy-val' || metadata.version !== '1.0.5') throw new Error(`No license text: ${metadata.name}@${metadata.version}`);
      const base = 'src/vendor/notices/lazy-val-1.0.5/';
      const provenance = JSON.parse(record(base + 'provenance.json'));
      const original = record(base + 'upstream-package.json');
      record(base + 'NOTICE.md');
      if (provenance.upstream_license_text_verified !== false || provenance.package_metadata_sha256 !== sha256(original)
          || JSON.parse(original).version !== metadata.version || JSON.parse(original).name !== metadata.name
          || metadata.license !== 'MIT' || JSON.parse(original).license !== metadata.license || provenance.package !== metadata.name) throw new Error('Invalid declared-only license evidence');
      status = 'declared_license_only_open_issue';
    } else notices.forEach(record);
    packages.push({ name: metadata.name, version: metadata.version, status });
  }
  if (!packages.length) throw new Error('No packaged runtime dependency inventory');
  return { schema_version: 1, legal_review_complete: false, packages, notices: records,
    open_issues: ['Native runtime license/source obligations require release review', ...packages.filter(p => p.status !== 'license_text_present').map(p => `${p.name}@${p.version}: upstream license full text not supplied`)] };
}
function auditOpenSsl(manifest, cryptoBytes, sslBytes) {
  if (!cryptoBytes && !sslBytes) return [];
  if (!cryptoBytes || !sslBytes) throw new Error('Incomplete packaged OpenSSL runtime pair');
  const versions = new Set([...cryptoBytes.toString('latin1').matchAll(/OpenSSL ([0-9]+\.[0-9]+\.[0-9]+[a-z]?) [^\x00]{1,40}/g)].map(match => match[1]));
  if (versions.size !== 1 || !versions.has('3.0.16')) throw new Error('Unreviewed packaged OpenSSL version');
  if (!manifest.components.some(c => c.name === 'OpenSSL' && c.version === '3.0.16')) throw new Error('Packaged OpenSSL notices missing');
  return [['libcrypto.3.dylib', cryptoBytes], ['libssl.3.dylib', sslBytes]].map(([name, bytes]) => ({ name, sha256: sha256(bytes), hash_stage: 'packaged-after-app-signing' }));
}
function auditBundle(resources) {
  const asar = require('@electron/asar');
  const archive = path.join(resources, 'app.asar');
  const result = auditArchive(asar.listPackage(archive), file => asar.extractFile(archive, file));
  result.external_notices = ['LICENSE.electron.txt', 'LICENSES.chromium.html'].map(name => {
    const candidates = [path.join(resources, name), path.join(resources, '..', name)];
    const file = candidates.find(p => fs.existsSync(p));
    if (!file || !fs.statSync(file).size) throw new Error(`Missing Electron notice: ${name}`);
    return { name, sha256: sha256(fs.readFileSync(file)) };
  });
  const backend = path.join(resources, 'backend', 'third-party-licenses');
  execFileSync('python', [path.resolve(__dirname, '../../../scripts/collect_backend_licenses.py'), '--check', '--destination', backend], { stdio: 'pipe' });
  const manifestBytes = fs.readFileSync(path.join(backend, 'manifest.json'));
  result.backend_manifest_sha256 = sha256(manifestBytes);
  const nativeBytes = name => { const file = path.join(resources, 'backend', '_internal', name); return fs.existsSync(file) ? fs.readFileSync(file) : null; };
  result.openssl_packaged_binaries = auditOpenSsl(JSON.parse(manifestBytes), nativeBytes('libcrypto.3.dylib'), nativeBytes('libssl.3.dylib'));
  return result;
}
if (require.main === module) {
  const resources = process.argv[2] || (process.platform === 'darwin' ? 'dist/mac-arm64/FootballAssistant.app/Contents/Resources' : 'dist/win-unpacked/resources');
  const output = process.argv[3];
  const text = JSON.stringify(auditBundle(path.resolve(resources)), null, 2) + '\n';
  if (output) fs.writeFileSync(output, text); else process.stdout.write(text);
}
module.exports = { auditArchive, auditBundle, auditOpenSsl };
