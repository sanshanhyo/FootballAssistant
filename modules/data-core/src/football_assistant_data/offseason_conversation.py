"""Bounded, process-session-scoped selection over the existing native reader.

User choices remain distinct from a validated native current-local-manager binding. No memory scanning,
new producer, filesystem persistence, or full-roster attribute fan-out lives here.
"""
import asyncio
import re
import time
from collections import OrderedDict
from uuid import uuid4

from football_assistant_agent.offseason_advice import prepare_offseason_advice


class OffseasonConversation:
    def __init__(self):
        self.sessions = OrderedDict()
        self.lock = asyncio.Lock()

    async def reply(self, body, read, agent):
        # Serial selection updates avoid conflicting confirmations, but a slow
        # model must not leave later user messages queued without a bounded reply.
        try:
            await asyncio.wait_for(self.lock.acquire(), timeout=1)
        except TimeoutError:
            from football_assistant_agent.service import ModelUnavailable
            raise ModelUnavailable("上一条读取或回复仍在处理，请稍后再试。") from None
        try:
            return await self._reply(body, read, agent)
        finally:
            self.lock.release()

    async def _reply(self, body, read, agent):
        conversation = body.conversation_id or str(uuid4())
        supplied = body.character_context.model_dump(exclude_none=True) if body.character_context else None
        scope = supplied or {}
        key = (scope.get('save_id', 'legacy'), scope.get('character_id', 'official.eckera'), conversation)
        # A new character/conversation must not resurrect a previous selection.
        for old in [k for k in self.sessions if k[0] == key[0] and k != key]:
            self.sessions.pop(old, None)
        now = time.monotonic()
        for expired in [k for k, v in self.sessions.items() if now - v['touched'] > 600]:
            self.sessions.pop(expired)
        envelope = await read(0, 0)
        initial = prepare_offseason_advice(envelope)
        if initial is None:
            self.sessions.pop(key, None)
            return None
        session = initial['session_id']
        manager = initial['facts'].get('current_manager')
        def manager_key(context):
            value = context['facts'].get('current_manager')
            return (value['uid'], value['team_uid'], value['club_uid']) if value else None
        binding = manager_key(initial)
        state = self.sessions.get(key)
        if state is None or state['session'] != session or state.get('binding') != binding:
            state = {'session': session, 'club': 0, 'pending': [], 'roster': [], 'team': None, 'team_at': 0, 'people': {}, 'last_selected': [], 'question': '', 'touched': now, 'binding': binding}
            if manager:
                state['club'] = manager['club_uid']
            self.sessions[key] = state
        state['touched'] = now
        self.sessions.move_to_end(key)
        while len(self.sessions) > 128:
            self.sessions.popitem(last=False)
        message = body.message.strip()
        if not state['question'] or re.search(r'谁.*(?:合适|适合)|哪个.*门将|which.*keeper', message, re.I):
            state['question'] = message
        def answer(text, context=initial):
            return {'status': 'partial', 'source_status': 'partial_native_candidates', 'reply': text,
                    'conversation_id': conversation, 'context': context,
                    **({'character_context': {name: scope[name] for name in ('save_id', 'character_id')}} if supplied else {})}
        def same(value):
            checked = prepare_offseason_advice(value)
            return checked is not None and checked['session_id'] == session and manager_key(checked) == binding
        candidates = initial['facts']['manager_club_candidates']
        person_markers = re.findall(r'(?:球员|人物|person|player)\s*UID\s*[:：#]?\s*([1-9][0-9]{0,9})\b', message, re.I)
        if not state['club'] and len(person_markers) == 1 and 0 < int(person_markers[0]) <= 2147483647:
            person = int(person_markers[0])
            selected = await read(0, person)
            if not same(selected):
                return answer('指定球员没有同一新鲜会话的读取结果。')
            return await agent.offseason_advice(message, conversation, selected, character_context=supplied, person_uid=person)
        # An explicitly supplied UID is a user selection, not inferred identity.
        club_markers = re.findall(r'(?:俱乐部|club)\s*UID\s*[:：#]?\s*([1-9][0-9]{0,9})\b', message, re.I)
        if len(club_markers) == 1 and 0 < int(club_markers[0]) < 0xffffffff:
            state.update(club=int(club_markers[0]), roster=[], team=None, people={}, last_selected=[], pending=[])
        elif state['pending']:
            allowed = {row['clubUid']: row for row in candidates if any(old['clubUid'] == row['clubUid'] for old in state['pending'])}
            if not allowed:
                state['pending'] = []
                return answer('上次待确认的球队候选已变化或不可用，请重新提出要查看的球队；不会沿用旧候选。')
            named = [row for row in allowed.values() if row['clubName'] in message]
            affirmative = re.fullmatch(r'(?:是|是的|对|对的|确认|就是这个|就是这支队|yes)[。！!，,\s]*', message, re.I)
            choice = named[0] if len(named) == 1 else next(iter(allowed.values())) if affirmative and len(allowed) == 1 else None
            if choice:
                state.update(club=choice['clubUid'], roster=[], team=None, people={}, last_selected=[], pending=[])
            elif re.search(r'门将|球队|队伍|阵容|球员|看一下|看看|确认|不是|不对', message):
                return answer('请先确认要看的球队名称：' + '、'.join(row['clubName'] for row in allowed.values()) + '。候选关联还不能证明当前执教身份。')
        relevant = bool(re.search(r'门将|球队|队伍|阵容|球员|首发|goalkeeper|squad|roster', message, re.I))
        if not state['club'] and relevant:
            unique = {row['clubUid']: row for row in candidates}
            if unique:
                state['pending'] = list(unique.values())
                return answer('已读到俱乐部关联候选：' + '、'.join(row['clubName'] for row in unique.values()) + '。你要看的是哪支球队？若只有这一支，回复“是的”即可；候选不代表已确认执教身份。')
        continuation = bool(re.fullmatch(r'(?:你看一下吧|再看看|比较一下|他们呢|怎么样)[。？?！!]*', message))
        names_mentioned = any(row['name'] in message for row in state['roster'])
        if manager and not relevant and not continuation and not names_mentioned and not club_markers and not person_markers:
            return await agent.offseason_advice(message, conversation, envelope, character_context=supplied)
        if not state['club']:
            return await agent.offseason_advice(message, conversation, envelope, character_context=supplied)
        club = state['club']
        if state['team'] is None or now - state['team_at'] > 25:
            team = await read(club, 0)
            if not same(team):
                state.update(roster=[], team=None, people={})
                return answer('这次所选球队的读取没有通过同一进程和新鲜度校验，请稍后再读；不会改查其他球队。')
            raw = (team.get('snapshot') or {}).get('team') or {}
            rows = raw.get('players')
            if raw.get('status') != 'experimental_candidates_incomplete' or not isinstance(rows, list) or len(rows) > 256:
                state.update(roster=[], team=None, people={})
                return answer('所选俱乐部的名单目前未知，不能据此判断门将。')
            roster = [r for r in rows if isinstance(r, dict) and type(r.get('uid')) is int and 0 < r['uid'] <= 2147483647 and r.get('clubUid') == club and r.get('linkStatus') == 'exact_types' and isinstance(r.get('name'), str) and 0 < len(r['name']) <= 128]
            state.update(roster=roster, team=team, team_at=now)
        roster = state['roster']
        team_context = prepare_offseason_advice(state['team'], club_uid=club)
        if team_context is None or manager_key(team_context) != binding:
            state.update(roster=[], team=None, people={}, last_selected=[])
            return answer('球队或当前经理的读取证据已失效，已停止使用旧名单，请重新提问。')
        projected_roster = {row['uid']: row for row in team_context['facts']['team_candidates']}
        ids = re.findall(r'(?:球员|人物|person|player)\s*UID\s*[:：#]?\s*([1-9][0-9]{0,9})\b', message, re.I)
        selected = [r for r in roster if str(r['uid']) in ids or r['name'] in message]
        by_name = {}
        for row in roster:
            by_name.setdefault(row['name'], set()).add(row['uid'])
        if any(len(by_name[r['name']]) > 1 and str(r['uid']) not in ids for r in selected):
            return answer('名单里有重名球员，请进一步确认要比较的是哪一位；不会猜身份。')
        selected = list({r['uid']: r for r in selected}.values())
        if not selected and re.fullmatch(r'(?:你看一下吧|再看看|比较一下|他们呢|怎么样)[。？?！!]*', message):
            selected = [r for r in roster if r['uid'] in state['last_selected']]
        if not selected and not ids and re.search(r'门将|goalkeeper|keeper', message + ' ' + state['question'], re.I):
            keepers = [row for row in roster if projected_roster.get(row['uid'], {}).get('positions', {}).get('is_goalkeeper') is True] if all(projected_roster.get(row['uid'], {}).get('positions') for row in roster) else []
            if len(keepers) > 2:
                return answer('本次名单中符合原生门将熟练度规则的有：' + '、'.join(row['name'] for row in keepers) + '。请先选至多两位姓名进行原始属性比较；不会漏读后声称比较了全部门将。')
            selected = keepers
        if len(selected) > 2 or re.search(r'不是|不要|排除|别选', message):
            return answer('请明确本次要看的至多两位球员姓名，我会只读取选定人员。')
        if ids and not selected:
            return answer('所给球员不在这次所选俱乐部的已读关联名单中，不能替你改查其他人。')
        if not selected:
            names = '、'.join(row['name'] for row in roster)
            if any(row.get('positions') for row in projected_roster.values()):
                return answer('已读到名单：' + (names or '暂未读到') + '。目前未能从完整有效的位置字段筛出可自动比较的门将，请直接说要比较的球员姓名（至多两位）；不会把缺失位置当作非门将。')
            return answer('已读到所选俱乐部的球员关联名单（可能不完整）：' + (names or '暂未读到') + '。当前接口没有球员位置，请说其中哪些是你要比较的实际门将（一次最多两位）；我会按需读取已有属性，不需要截图。')
        state['last_selected'] = [r['uid'] for r in selected]
        related = []
        for row in selected:
            cached = state['people'].get(row['uid'])
            value = cached[1] if cached and now - cached[0] <= 15 else await read(club, row['uid'])
            if not same(value):
                return answer('选定球员的读取不再属于同一新鲜会话，已停止比较，不会使用旧值。')
            state['people'][row['uid']] = (now, value)
            related.append({'person_uid': row['uid'], 'envelope': value})
        return await agent.offseason_advice((state['question'] + '\n本轮用户补充：' + message) if state['question'] and state['question'] != message else message, conversation, state['team'], character_context=supplied, club_uid=club, related_people=related)
