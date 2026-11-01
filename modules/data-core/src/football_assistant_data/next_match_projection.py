"""One pinned viewed-club next-match UI card, never the manager's team or schedule."""
from datetime import date
import hashlib
import json
import re
import unicodedata
from .display_profile import GAME_BUILD, _require

PROFILE_ID = 'fm27-27.0.0+2486695-zh-focused-next-match-alpha-v1'
FOCUS_ROOT = 'panel0/0/6/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/1/0/0/0/2'
TITLE_PATH = 'focus/0/0/0/0/0/0/0'
OPPONENT_PATH = 'focus/0/0/0/0/0/1/0/1/0/0'
COMPETITION_PATH = 'focus/0/0/0/0/0/1/0/1/1/0/0/0/0'
DISPLAY_FIELDS = ('date_display', 'opponent_display', 'competition_display')
LIMITATIONS = [
    '仅为当前查看俱乐部页面的下一场比赛卡片，不是用户执教球队的确认信息，也不是完整赛程。',
    '只能说“你这页的下一场……如果说的是它……”并给条件建议；球队身份、比赛ID、主客场、开球时间均未知。',
    '球员体能、伤情、实力、后续赛程与游戏当前日期未读取；不能推算休息天数或指定某名球员轮换。',
    '可给友谊赛轮换和练配合等足球经验判断，但不能虚构赛况；页面可能包含隐藏或缓存文本。',
    '来源路径、采样时间、原始标题和身份元数据仅保留本地，不提供给模型。',
]


def _text(value, *, display_markup=False):
    _require(isinstance(value, str) and 0 < len(value) <= 256, 'invalid_next_match_text')
    if display_markup and ('<' in value or '>' in value):
        # Sole observed card wrapper. link="0" is formatting, never an entity ID.
        wrapped = re.fullmatch(r'<color="#FFFFFF"><link="0"><style="Norml">([^<>]+)</style></link></color>', value)
        _require(wrapped is not None, 'unsupported_next_match_markup')
        value = wrapped[1]
    value = value.replace('\u200b', '')
    _require(value == value.strip() and bool(value) and all(
        unicodedata.category(c)[0] in ('L', 'N', 'P') or c == ' ' for c in value), 'invalid_next_match_text')
    return value


def project_validated_next_match(texts, *, game, source, provenance, capture_text_sha256):
    result = dict(status='unavailable', reason='unsupported_layout', profile_id=PROFILE_ID,
                  kind='next_match', source='ui', experimental=True, partial=True, production_ready=False,
                  schedule_complete=False, identity=None, managed_team=None, business_identity_known=False,
                  fixture_id=None, home_away_display=None, kickoff_time=None,
                  date_display=None, opponent_display=None, competition_display=None,
                  field_provenance={}, raw_texts={}, limitations=list(LIMITATIONS), projection_sha256=None)
    try:
        _require(game.get('product') == 'FM27' and game.get('build') == GAME_BUILD, 'unsupported_build')
        _require(source.get('platform') == 'macos-arm64', 'unsupported_platform')
        _require(provenance.get('path_scope') == 'focus_relative'
                 and provenance.get('focus_root_path') == FOCUS_ROOT
                 and provenance.get('identity_scope') == 'capture_local_ui_path', 'unsupported_layout')
        paths = {}
        for item in texts:
            _require(item['path'] not in paths, 'duplicate_path')
            paths[item['path']] = item['text']
        refs = dict(date_display=TITLE_PATH, opponent_display=OPPONENT_PATH, competition_display=COMPETITION_PATH)
        _require(all(path in paths for path in refs.values()), 'missing_next_match_field')
        values = {key: _text(paths[path], display_markup=key != 'date_display') for key, path in refs.items()}
        _require(all(any(unicodedata.category(c).startswith('L') for c in values[key])
                     for key in ('opponent_display', 'competition_display')), 'invalid_next_match_text')
        match = re.fullmatch(r'下一场比赛（([0-9]{4})-([1-9]|1[0-2])-([1-9]|[12][0-9]|3[01])）', values['date_display'])
        _require(match is not None, 'invalid_next_match_title')
        date(*(int(part) for part in match.groups()))  # Validate calendar only; do not infer game date.
        values['date_display'] = '-'.join(match.groups())
        result.update(**values, status='experimental_ui_next_match', reason='matched_pinned_layout',
                      raw_texts={key: paths[path] for key, path in refs.items()},
                      field_provenance={key: {**provenance, 'ui_path': path, 'profile_id': PROFILE_ID,
                          'capture_text_sha256': capture_text_sha256} for key, path in refs.items()},
                      projection_sha256=hashlib.sha256(json.dumps(dict(profile=PROFILE_ID, values=values,
                          provenance=provenance, capture_text_sha256=capture_text_sha256), sort_keys=True).encode()).hexdigest())
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        reason = str(error)
        result['reason'] = reason if re.fullmatch(r'[a-z_]{1,40}', reason) else 'invalid_next_match_capture'
    return result
