'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { characterPresentation } = require('./character.cjs');
const metadata = require('../package.json');
const REPOSITORY = 'https://github.com/sanshanhyo/FootballAssistant';
const CONTRIBUTORS = `${REPOSITORY}/graphs/contributors`;
function createSettingsContent({ version, openExternal }) {
  return {
    async introduction() {
      const file = path.join(__dirname, 'assets', 'role-introduction.md');
      const bytes = await fs.readFile(file);
      if (bytes.length > 16384) throw Error('角色介绍超出长度限制。');
      return { content: new TextDecoder('utf-8', { fatal: true }).decode(bytes), character: characterPresentation() };
    },
    about() {
      return { version: typeof version === 'string' && version.length <= 128 ? version : metadata.version,
        name: metadata.build.productName, description: metadata.description,
        author: typeof metadata.author === 'string' ? metadata.author : null,
        repository: REPOSITORY, contributorsUrl: CONTRIBUTORS };
    },
    async openRepository() { await openExternal(REPOSITORY); return { opened: true }; },
    async openContributors() { await openExternal(CONTRIBUTORS); return { opened: true }; },
  };
}
module.exports = { createSettingsContent };
