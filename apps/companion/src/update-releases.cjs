'use strict';
const { REPOSITORY, compareVersions } = require('./update-security.cjs');
const RELEASES_API = `https://api.github.com/repos/${REPOSITORY}/releases`;
// Public metadata only: never accept API/asset URLs, tokens or executable content
// from the response. Canonical release links are constructed from validated tags.
async function checkPublicAlphaReleases({ fetchImpl, signal, currentVersion }) {
  let latest = null;
  for (let page = 1; page <= 10; page++) {
    const response = await fetchImpl(`${RELEASES_API}?per_page=100&page=${page}`, {
      redirect: 'error', credentials: 'omit', signal,
      headers: { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' }
    });
    if (!response.ok) throw new Error(`GitHub release check failed (HTTP ${response.status}); repository may be private/unavailable or rate-limited`);
    if (!response.body) throw new Error('Empty GitHub response');
    let size = 0; const chunks = [];
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 2 * 1024 * 1024) throw new Error('GitHub release metadata exceeds safety limit');
      chunks.push(Buffer.from(chunk));
    }
    const releases = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!Array.isArray(releases)) throw new Error('Invalid GitHub releases response');
    for (const release of releases) {
      if (!release || release.draft !== false || release.prerelease !== true || typeof release.tag_name !== 'string' || !/^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-alpha\.(0|[1-9]\d*)$/.test(release.tag_name)) continue;
      const version = release.tag_name.replace(/^v/, '');
      if (!latest || compareVersions(version, latest.version) > 0) latest = { version, tag: release.tag_name };
    }
    if (releases.length < 100) {
      if (!latest) return { state: 'no_release', reason: 'No published Alpha prerelease matching [v]X.Y.Z-alpha.N', availableVersion: null, releaseUrl: null };
      if (compareVersions(latest.version, currentVersion) <= 0) return { state: 'up_to_date', reason: null, availableVersion: null, releaseUrl: null };
      return { state: 'update_available', availableVersion: latest.version, releaseUrl: `https://github.com/${REPOSITORY}/releases/tag/${encodeURIComponent(latest.tag)}`, reason: 'New Alpha release listed on GitHub. Package signature and platform compatibility are not verified; review the release and install manually.' };
    }
  }
  throw new Error('Release history exceeds check limit; result is inconclusive');
}
module.exports = { RELEASES_API, checkPublicAlphaReleases };
