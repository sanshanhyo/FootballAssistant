"""Experimental, capture-local schedule associations; never native fixture records.

Called only with the validated full capture from prepare_ui_advice. Selectors are
pinned to one observed Chinese layout. Missing rows are never filled or cached.
"""
import hashlib
import json
import re

from .display_profile import GAME_BUILD, _plain, _require

PROFILE_ID = 'fm27-27.0.0+2486695-zh-focused-schedule-alpha-v1'
FOCUS_ROOT = 'panel0/0/4/0/0/0/0/0/1/0/0/0/0/0/0/1/0/5'
TITLE_PATH = 'focus/0/0/0/0/0/0/0/0/1/1/0/0/0/0/0'
ROW_PREFIX = 'focus/0/0/0/0/0/0/0/0/1/1/0/1/0/0/0/2/0/0/'
COLUMNS = {
    'date_display': '/0/0/0/0',
    'opponent_display': '/1/0/0/0/0/0/0/0/0/0/0/1',
    'home_away_display': '/2/0/0/0',
    'competition_display': '/4/0/0/0/0/0/0/1',
}
LIMITATIONS = [
    '实验性中文赛程 UI 行关联，不是原生赛程、球队身份或完整赛程；行号仅为本次采样坐标。',
    '只输出本次完整读取的四列；未采到的行、开球时间、球场、结果和球队 ID 均未知。',
    '两位年份的世纪未经验证，保留显示日期与年月日分量；ISO 日期未知，不计算完整赛程密度或跨年休息天数。',
    '页面标题匹配不证明当前可见性；隐藏或缓存文本仍可能存在。',
]


def project_validated_schedule(texts, *, game, source, provenance, capture_text_sha256):
    """Associate only validated current-capture texts (not an unvalidated API input)."""
    result = dict(status='unavailable', reason='unsupported_layout', profile_id=PROFILE_ID,
                  experimental=True, source='ui', partial=True, production_ready=False,
                  business_identity_known=False, rows=[], limitations=list(LIMITATIONS),
                  projection_sha256=None)
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
        _require(paths.get(TITLE_PATH) == '赛程安排', 'unsupported_title_or_locale')
        indices = set()
        for path in paths:
            if path.startswith(ROW_PREFIX):
                index, separator, _ = path[len(ROW_PREFIX):].partition('/')
                _require(separator and re.fullmatch(r'[0-9]', index), 'unsupported_row_layout')
                indices.add(int(index))
        rows = []
        for index in sorted(indices):
            refs = {key: ROW_PREFIX + str(index) + suffix for key, suffix in COLUMNS.items()}
            values = {key: _plain(paths[path]) for key, path in refs.items() if path in paths}
            # Even an incomplete row's observed columns must obey the profile.
            if 'date_display' in values:
                match = re.fullmatch(r'([0-9]{2})-([1-9]|1[0-2])-([1-9]|[12][0-9]|3[01])', values['date_display'])
                _require(match is not None, 'invalid_date_display')
                year, month, day = map(int, match.groups())
                # Century is unknown; February 29 is possible only in years divisible by 4.
                max_day = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
                _require(day <= max_day, 'invalid_date_display')
            if 'home_away_display' in values:
                _require(values['home_away_display'] in ('主', '客'), 'unsupported_home_away')
            if len(values) != len(COLUMNS):
                continue
            field_provenance = {key: {**provenance, 'ui_path': path, 'title_path': TITLE_PATH,
                                      'profile_id': PROFILE_ID, 'game_build': GAME_BUILD,
                                      'adapter_version': source['adapter_version'],
                                      'capture_text_sha256': capture_text_sha256}
                                for key, path in refs.items()}
            field_provenance['date_components'] = dict(field_provenance['date_display'])
            rows.append(dict(row_index=index, identity_scope='capture_local_ui_path', **values,
                             date_components=dict(year_two_digits=year, month=month, day=day),
                             date_iso=None, kickoff=None, field_provenance=field_provenance))
        _require(bool(rows), 'no_complete_rows')
        fingerprint = hashlib.sha256(json.dumps(dict(profile=PROFILE_ID, game=game, source=source,
                    capture_text_sha256=capture_text_sha256), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        result.update(status='experimental_ui_schedule', reason='matched_pinned_layout', rows=rows,
                      projection_sha256=fingerprint)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        reason = str(error)
        result['reason'] = reason if re.fullmatch(r'[a-z_]{1,40}', reason) else 'invalid_schedule_capture'
    return result
