"""Narrow, deterministic protection for unverified user-managed team identity."""
import re


def asks_managed_team(message):
    if not isinstance(message, str):
        return False
    value = re.sub(r'\s+', '', message)
    if re.search(r'适合|推荐|选择|挑选|该选|想去|开始执教', value) or re.search(r'\b(?:should|could|would|recommend)\b', message, re.I):
        return False  # Team-selection opinions are not current managed-team identity queries.
    chinese = (
        bool(re.search(r'我(?:们)?(?:现在|目前|当前|这会儿|正在|在|是|到底|究竟|已经|还|刚|正|的){0,4}(?:执掌|执教|带队|管理|主教练|教练)'
                       r'|我(?:们)?(?:现在|目前|当前)?(?:在|是)?哪'
                       r'|我(?:们)?的(?:球队|队|俱乐部)', value))
        and bool(re.search(r'球队|俱乐部|哪(?:一|个|支)?队|什么队|哪个队|我的队|我们的队', value))
        and bool(re.search(r'哪(?:一|个|支|家)?(?:球队|俱乐部|队)|(?:球队|俱乐部|队)(?:叫|是什么|是谁|是哪|的?名字|名)|队名', value))
    )
    english = bool(re.search(
        r'\b(?:which|what)\s+(?:team|club)\b.*\b(?:i|we)\b.*\b(?:manag\w*|coach\w*)\b'
        r'|\b(?:which|what)\s+is\s+(?:my|our)\s+(?:team|club)\b', message, re.I))
    return chinese or english


def managed_team_unconfirmed(conversation_id, *, mode):
    # No inferred team name, player-club promotion, history, provider or memory access.
    return dict(status='blocked', mode=mode, source='unknown', partial=True, production_ready=False,
                source_status='managed_team_unconfirmed', capability='player_info',
                conversation_id=conversation_id, identity=None, provenance=None,
                evidence=[], facts=[], schedule_projection=None, tactics_projection=None,
                limitations=['执教球队身份尚未得到当前可靠来源确认；球员俱乐部不等于执教球队。'],
                reasons=['managed_team_identity_unverified'],
                missing_requirements=['verified_managed_team_identity'],
                reply='你现在执教哪支队，我还没确认准。球员所属的俱乐部不一定是你的队，我先不猜队名。')
