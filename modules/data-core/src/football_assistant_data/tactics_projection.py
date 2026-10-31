"""Pinned, capture-local tactical display projection; never native tactical entities.

Call only after prepare_ui_advice has validated the full, fresh runtime capture.
The title association was observed on the normal Chinese panel layout; neither
paths nor the title establish current visibility, team identity or player roles.
"""
import hashlib
import json
import re
import unicodedata

from .display_profile import GAME_BUILD, _require

PROFILE_ID = 'fm27-27.0.0+2486695-zh-panel-tactics-alpha-v1'
PANEL_ROOT = 'panel0/0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0'
TITLE_PATH = PANEL_ROOT + '/0/0/0/0/1/0/0/1/0'
STYLE_PATH = PANEL_ROOT + '/0/0/1/0/0/0/0/0/0'
MENTALITY_PATH = PANEL_ROOT + '/0/0/2/0/0/1/0/1'
LABEL_PATH = PANEL_ROOT + '/2/0/0/0/0/0'
DISPLAY_FIELDS = ('formation_display', 'style_display', 'mentality_display')
LIMITATIONS = [
    '实验性 UI 战术显示，仅包含阵型描述、风格和心态，不是原生战术或完整球队事实。',
    '首发、球员身份、位置职责、个人与团队指令均未读取，未知而非为空；不得据此推断。',
    '页面名称与当前可见性未经独立验证，可能包含隐藏或缓存文本；只能给有条件的建议。',
    '来源路径、采样时间和身份元数据仅保留在本地，未提供给模型；不得编造。',
]


def _display(value):
    _require(isinstance(value, str), 'invalid_tactics_text')
    value = value.replace('\u200b', '')  # The sole observed normalization; do not strip or fold.
    _require(0 < len(value) <= 128 and value == value.strip() and
             all(unicodedata.category(c)[0] in ('L', 'N') or c in ' -' for c in value),
             'invalid_tactics_text')
    return value


def project_validated_tactics(texts, *, game, source, provenance, capture_text_sha256):
    result = dict(status='unavailable', reason='unsupported_layout', profile_id=PROFILE_ID,
                  experimental=True, source='ui', partial=True, production_ready=False,
                  business_identity_known=False, formation_display=None, style_display=None,
                  mentality_display=None, lineup=None, roles=None, instructions=None,
                  field_provenance={}, raw_texts={}, limitations=list(LIMITATIONS), projection_sha256=None)
    try:
        _require(game.get('product') == 'FM27' and game.get('build') == GAME_BUILD, 'unsupported_build')
        _require(source.get('platform') == 'macos-arm64', 'unsupported_platform')
        focused = (provenance.get('path_scope') == 'focus_relative'
                   and provenance.get('focus_root_path') == PANEL_ROOT)
        absolute = (provenance.get('path_scope') == 'panel_absolute'
                    and provenance.get('focus_root_path') is None)
        _require((focused or absolute) and provenance.get('identity_scope') == 'capture_local_ui_path',
                 'unsupported_layout')
        paths = {}
        for item in texts:
            _require(item['path'] not in paths, 'duplicate_path')
            paths[item['path']] = item['text']
        refs = dict(title=TITLE_PATH, style_display=STYLE_PATH, mentality_display=MENTALITY_PATH, label=LABEL_PATH)
        if focused:
            result['profile_id'] = PROFILE_ID + '-focused'
            refs = {key: 'focus' + path[len(PANEL_ROOT):] for key, path in refs.items()}
        _require(all(path in paths for path in refs.values()), 'missing_tactics_field')
        values = {key: _display(paths[path]) for key, path in refs.items()}
        _require(values['label'] == '队形', 'unsupported_title_or_locale')
        title, style, mentality = values['title'], values['style_display'], values['mentality_display']
        _require(all(unicodedata.category(c).startswith('L') or c == ' ' for c in style + mentality),
                 'invalid_tactics_text')
        suffix = ' - ' + style
        _require(title.startswith(mentality) and title.endswith(suffix), 'tactics_title_mismatch')
        formation = title[len(mentality):-len(suffix)]
        _require(formation == formation.strip() and ' - ' not in formation, 'invalid_formation_display')
        match = re.fullmatch(r'([1-9](?:-[1-9]){1,4})(?: (.+))?', formation)
        _require(match is not None and sum(map(int, match.group(1).split('-'))) == 10,
                 'invalid_formation_display')
        descriptor = match.group(2)
        if descriptor is not None:
            _require(descriptor[0].isalnum() and descriptor[-1].isalnum()
                     and any(unicodedata.category(c).startswith('L') for c in descriptor),
                     'invalid_formation_display')
        field_refs = dict(formation_display=refs['title'], style_display=refs['style_display'], mentality_display=refs['mentality_display'])
        field_provenance = {key: {**provenance, 'ui_path': path, 'title_path': refs['title'],
                                 'profile_id': result['profile_id'], 'game_build': GAME_BUILD,
                                 'adapter_version': source['adapter_version'],
                                 'capture_text_sha256': capture_text_sha256}
                            for key, path in field_refs.items()}
        fingerprint = hashlib.sha256(json.dumps(dict(profile=result['profile_id'], game=game, source=source,
                    capture_text_sha256=capture_text_sha256), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        result.update(status='experimental_ui_tactics', reason='matched_pinned_layout',
                      formation_display=formation, style_display=style, mentality_display=mentality,
                      field_provenance=field_provenance, raw_texts={key: paths[path] for key, path in refs.items()},
                      projection_sha256=fingerprint)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        reason = str(error)
        result['reason'] = reason if re.fullmatch(r'[a-z_]{1,40}', reason) else 'invalid_tactics_capture'
    return result
