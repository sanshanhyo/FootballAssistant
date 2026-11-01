'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { request } = require('../src/backend.cjs');
const { RealReaderClient } = require('../src/reader-clients.cjs');
const { calendarEndpoint, isCalendarEndpoint } = require('../src/offseason-calendar.cjs');

test('calendar selector validates bounds and uses canonical fixed endpoint', () => {
  assert.equal(calendarEndpoint(42, '2026-02-01', '2026-03-02'), '/v1/reader/offseason?club_uid=42&start=2026-02-01&end=2026-03-02');
  for (const args of [[0,'2026-02-01','2026-02-02'],[42,'2026-02-30','2026-03-01'],[42,'2026-02-01','2026-03-03'],[42,'2026-12-31','2027-01-01'],[42,'2026-03-01','2026-02-28'],[42,'2026-2-01','2026-02-02']]) assert.throws(() => calendarEndpoint(...args));
  for (const endpoint of ['/v1/reader/offseason?club_uid=42&start=2026-02-01&end=2026-02-02&x=1','/v1/reader/offseason?club_uid=042&start=2026-02-01&end=2026-02-02','/v1/reader/offseason?club_uid=42&start=2026-02-01&end=2026-02-02%26x=1']) assert.equal(isCalendarEndpoint(endpoint), false);
});

test('client forwards partial and unknown unchanged, with abort and 45s timeout', async () => {
  const controller = new AbortController(); let called;
  const value = { status: 'partial', snapshot: { calendar: { status: 'partial', unloaded: 3, unknown: 2, fixtures: [] } } };
  const client = new RealReaderClient({ request: async (...args) => { called = args; return value; } });
  assert.equal(await client.offseasonCalendar({ clubUid: 42, start: '2026-02-01', end: '2026-02-02', signal: controller.signal }), value);
  assert.equal(called[0], '/v1/reader/offseason?club_uid=42&start=2026-02-01&end=2026-02-02');
  assert.equal(called[2].timeoutMs, 45000); assert.equal(called[2].signal, controller.signal);
});

test('transport allows only validated calendar URL, attaches auth, and cancels', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'fa-calendar-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const runtime = path.join(dir, 'runtime.json');
  await fs.writeFile(runtime, JSON.stringify({base_url:'http://127.0.0.1:1234',token:'test-secret-not-for-renderer'}));
  const endpoint = calendarEndpoint(42, '2026-02-01', '2026-02-02');
  let seen;
  const result = await request(runtime, endpoint, undefined, { fetch: async (url, options) => { seen = {url, options}; return {ok:true,text:async()=>JSON.stringify({status:'partial', snapshot:{calendar:{status:'partial',unknown:1}}})}; } });
  assert.equal(seen.options.headers.Authorization, 'Bearer test-secret-not-for-renderer');
  assert.equal(seen.url, 'http://127.0.0.1:1234' + endpoint); assert.equal(result.snapshot.calendar.unknown, 1);
  await assert.rejects(request(runtime, endpoint, undefined, {fetch: async () => ({status:401, ok:false, text:async()=> '{}'})}), error => error.code === 'unauthorized');
  await assert.rejects(request(runtime, endpoint, undefined, {timeoutMs:10, fetch: async (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), {once:true}))}), /超时/);
  await assert.rejects(request(runtime, endpoint + '&x=1', undefined), /./);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(request(runtime, endpoint, undefined, {signal:controller.signal}), {name:'AbortError'});
});

test('calendar advice sends only explicit selection and question, not caller supplied facts', async () => {
  let called;
  const client = new RealReaderClient({ request: async (...args) => { called = args; return {status:'partial', context:{status:'partial'}}; } });
  const result = await client.calendarAdvice({ message:'What is the schedule?', clubUid:42, start:'2026-02-01', end:'2026-02-10', fixtures:[{name:'injected'}] });
  assert.equal(result.status, 'partial');
  assert.equal(called[0], '/v1/agent/calendar-advice');
  assert.deepEqual(called[1], {message:'What is the schedule?', conversation_id:null, club_uid:42, start:'2026-02-01', end:'2026-02-10'});
  await assert.rejects(client.calendarAdvice({ message:'question', clubUid:0, start:'2026-02-01', end:'2026-02-10' }));
});
