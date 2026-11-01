'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { compareVersions, REPOSITORY } = require('../src/update-security.cjs');
const { checkPublicAlphaReleases } = require('../src/update-releases.cjs');
function requireAlpha(version) {
  if (typeof version !== 'string' || !/^\d+\.\d+\.\d+-alpha\.\d+$/.test(version)) throw Error('Use X.Y.Z-alpha.N');
  compareVersions(version, version);
}
function validateAdvance(version, previousVersion, sourceVersion, publishedVersion) {
  requireAlpha(version); requireAlpha(previousVersion);
  if (compareVersions(version, previousVersion) <= 0 || compareVersions(version, sourceVersion) <= 0 ||
      (publishedVersion && compareVersions(version, publishedVersion) <= 0)) throw Error('Alpha release version must strictly exceed source, previous and published versions; never replace a version');
}
async function prepare({ appRoot, version, previousVersion, fetchImpl = globalThis.fetch }) {
  const packageFile = path.join(appRoot, 'package.json'), lockFile = path.join(appRoot, 'package-lock.json');
  const pkg = JSON.parse(fs.readFileSync(packageFile, 'utf8')), lock = JSON.parse(fs.readFileSync(lockFile, 'utf8'));
  validateAdvance(version, previousVersion, pkg.version);
  const published = await checkPublicAlphaReleases({ fetchImpl, signal: AbortSignal.timeout(30000), currentVersion: '0.0.0-alpha.0' });
  validateAdvance(version, previousVersion, pkg.version, published.availableVersion);
  if (lock.version !== pkg.version || lock.packages?.['']?.version !== pkg.version) throw Error('Package/lock versions differ');
  const record = { version, previousVersion, sourceVersion: pkg.version, publishedVersion: published.availableVersion,
    commit: process.env.GITHUB_SHA || null, repository: REPOSITORY, prerelease: true, published: false };
  pkg.version = version; lock.version = version; lock.packages[''].version = version;
  fs.writeFileSync(packageFile, JSON.stringify(pkg, null, 2) + '\n');
  fs.writeFileSync(lockFile, JSON.stringify(lock, null, 2) + '\n');
  fs.writeFileSync(path.join(appRoot, 'alpha-preparation.json'), JSON.stringify(record, null, 2) + '\n');
  return record;
}
function releaseMetadata({ version, previousVersion, name, size, sha256, sha512, now = new Date() }) {
  requireAlpha(version); requireAlpha(previousVersion);
  if (compareVersions(version, previousVersion) <= 0 || name !== `FootballAssistant-${version}-Setup-x64.exe` || !Number.isSafeInteger(size) || size <= 0 || !/^[a-f0-9]{64}$/.test(sha256) || !/^[A-Za-z0-9+/]{86}==$/.test(sha512)) throw Error('Invalid release inputs');
  const base = `https://github.com/${REPOSITORY}/releases/download/${version}/`;
  const nativeMetadata = `version: ${version}\nfiles:\n  - url: ${name}\n    sha512: ${sha512}\n    size: ${size}\npath: ${name}\nsha512: ${sha512}\nreleaseDate: '${now.toISOString()}'\n`;
  const plan = { version, previousVersion, prerelease: true, published: false, immutableTag: version,
    immutableAssets: [name, `${name}.blockmap`, 'alpha.yml'], installer: { size, sha256, sha512, url: base + name },
    channelTag: 'alpha-channel', channelAsset: 'alpha-update.json', publicationOrder: ['Upload all immutable version assets', 'Verify public immutable assets and hashes', 'Replace channel manifest last'],
    signature: 'Ed25519 manifest with installer SHA256; not Windows Authenticode', portableAutomaticReplacement: false };
  return { nativeMetadata, plan };
}
if (require.main === module) prepare({ appRoot: path.resolve(__dirname, '..'), version: process.env.FA_ALPHA_VERSION, previousVersion: process.env.FA_ALPHA_PREVIOUS_VERSION })
  .then(record => console.log(`Prepared ${record.version}; no release published.`)).catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = { prepare, validateAdvance, releaseMetadata };
