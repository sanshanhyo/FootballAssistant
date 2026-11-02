'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
function identity({ version, commit, runId = '', runAttempt = '', ref = '' }) {
  if (!/^\d+\.\d+\.\d+-alpha\.\d+$/.test(version) || !/^[a-f0-9]{40}$/.test(commit)) throw new Error('Version and exact source SHA required');
  return { schema: 1, version, commit, runId, runAttempt, ref, releasePublished: false, realGameAcceptance: 'pending' };
}
if (require.main === module) {
  const appRoot = path.resolve(__dirname, '..');
  const result = identity({ version: require(path.join(appRoot, 'package.json')).version,
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: appRoot, encoding: 'utf8' }).trim(),
    runId: process.env.GITHUB_RUN_ID, runAttempt: process.env.GITHUB_RUN_ATTEMPT, ref: process.env.GITHUB_REF });
  fs.writeFileSync(path.join(appRoot, 'build-identity.json'), JSON.stringify(result, null, 2) + '\n');
}
module.exports = { identity };
