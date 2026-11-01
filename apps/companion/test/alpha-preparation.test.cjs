'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {prepare,validateAdvance,releaseMetadata}=require('../packaging/prepare-alpha.cjs');
test('Alpha rolling versions are numeric, immutable and strictly advance past source and published versions',()=>{
 assert.doesNotThrow(()=>validateAdvance('0.0.1-alpha.10','0.0.1-alpha.9','0.0.1-alpha.1','0.0.1-alpha.8'));
 for(const args of [['0.0.1-alpha.1','0.0.1-alpha.1','0.0.1-alpha.1'],['0.0.1-alpha.9','0.0.1-alpha.8','0.0.1-alpha.1','0.0.1-alpha.10'],['0.0.2','0.0.1-alpha.1','0.0.1-alpha.1'],['0.0.1-alpha.01','0.0.1-alpha.0','0.0.1-alpha.0']])assert.throws(()=>validateAdvance(...args));
});
test('prepare changes only build checkout versions after checking public prereleases, never publishes',async t=>{
 const appRoot=fs.mkdtempSync(path.join(os.tmpdir(),'fa-alpha-prep-'));t.after(()=>fs.rmSync(appRoot,{recursive:true,force:true}));
 const version='0.0.1-alpha.1';fs.writeFileSync(path.join(appRoot,'package.json'),JSON.stringify({name:'fixture',version}));fs.writeFileSync(path.join(appRoot,'package-lock.json'),JSON.stringify({version,packages:{'':{version}}}));
 const calls=[];const fetchImpl=async(url,options)=>{calls.push({url,options});return Response.json([{tag_name:'0.0.1-alpha.2',draft:false,prerelease:true}]);};
 await assert.rejects(prepare({appRoot,version:'0.0.1-alpha.2',previousVersion:version,fetchImpl}));assert.equal(JSON.parse(fs.readFileSync(path.join(appRoot,'package.json'))).version,version);
 const result=await prepare({appRoot,version:'0.0.1-alpha.3',previousVersion:'0.0.1-alpha.2',fetchImpl});
 assert.equal(result.published,false);assert.equal(JSON.parse(fs.readFileSync(path.join(appRoot,'package-lock.json'))).packages[''].version,result.version);
 assert.equal(calls.every(x=>!x.options.method && !x.options.headers.Authorization),true);
});
test('native metadata and publication plan bind one exact installer, with channel manifest updated last',()=>{
 const bytes=Buffer.from('synthetic installer'),version='0.0.1-alpha.2';const sha256=crypto.createHash('sha256').update(bytes).digest('hex'),sha512=crypto.createHash('sha512').update(bytes).digest('base64');
 const value=releaseMetadata({version,previousVersion:'0.0.1-alpha.1',name:`FootballAssistant-${version}-Setup-x64.exe`,size:bytes.length,sha256,sha512,now:new Date('2026-01-01T00:00:00Z')});
 assert.ok(value.nativeMetadata.includes(`version: ${version}\n`));assert.ok(value.nativeMetadata.includes(`sha512: ${sha512}`));assert.equal(value.plan.installer.sha256,sha256);
 assert.equal(value.plan.prerelease,true);assert.equal(value.plan.published,false);assert.equal(value.plan.publicationOrder.at(-1),'Replace channel manifest last');assert.match(value.plan.signature,/not Windows Authenticode/);
});
