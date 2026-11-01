'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createSettingsContent } = require('../src/settings-content.cjs');
const { allowsWindowIpc } = require('../src/companion-security.cjs');
const metadata = require('../package.json');
test('introduction is separate packaged Markdown and uses existing character PNG', async () => {
  const service = createSettingsContent({version:'test-version',openExternal:async()=>{}});
  const result = await service.introduction();
  assert.match(result.content,/有主见、温和又有点俏皮的足球伙伴/); assert.equal(result.character.displayName,'埃克拉'); assert.doesNotMatch(result.content, /^#/); assert.equal(result.character.visual.source,'assets/characters/official.eckera/default.png');
  assert.equal(Object.hasOwn(result,'persona'),false);
});
test('about uses actual version and package authors, links are fixed not renderer input', async () => {
  const opened=[]; const service=createSettingsContent({version:'test-version',openExternal:async url=>opened.push(url)});
  assert.equal(service.about().version,'test-version'); assert.equal(service.about().author,metadata.author);
  await service.openRepository('https://untrusted.invalid'); await service.openContributors('file:///tmp/secret');
  assert.deepEqual(opened,['https://github.com/sanshanhyo/FootballAssistant','https://github.com/sanshanhyo/FootballAssistant/graphs/contributors']);
});
test('persona content and fixed-link IPC are restricted to trusted settings mainframe',()=>{
  const current={role:'settings',trustedMainFrame:true,currentUrl:'file:///settings',pageUrl:'file:///settings'};
  for(const method of ['persona-get','persona-save','character-introduction','about-get','repository-open','contributors-open']) {
    assert.equal(allowsWindowIpc(current,method),true);
    assert.equal(allowsWindowIpc({...current,role:'pet'},method),false);
    assert.equal(allowsWindowIpc({...current,trustedMainFrame:false},method),false);
  }
});
