"""Capture-local attribute label/value pairs, with deliberately unknown identity.

This is a local, model-free preview, not a player record or an advice input.
Only call after the common runtime UI capture gate validates the entire snapshot.
"""
import hashlib
import json
import re

from .display_profile import GAME_BUILD, _require

PROFILE_ID = 'fm27-27.0.0+2486695-zh-focused-page-attributes-alpha-v1'
FOCUS_ROOT = 'panel0/0/6'
COMMON_PREFIX = 'focus/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0'
LABEL_SUFFIX = '/0/0/0/0/0/0/0/0/0'
VALUE_SUFFIX = '/0/0/0/0/0/0/1/1/0/0/0/0/0/0'
CATEGORIES = {
    'goalkeeper': dict(labels=('出击(倾向)', '传球', '大脚开球', '反应', '拦截传中', '拳击球(倾向)', '手控球', '手抛球', '停球', '一对一', '意外性', '指挥防守', '制空范围'), title='守门', title_path=COMMON_PREFIX + '/0/0/0', row_prefix=COMMON_PREFIX + '/0/0/2/0/0/0/'),
    'mental': dict(labels=('才华', '防守站位', '工作投入', '集中', '决断', '领导力', '侵略性', '视野', '团队合作', '无球跑动', '意志力', '勇敢', '预判', '镇定'), title='精神', title_path=COMMON_PREFIX + '/1/0/0', row_prefix=COMMON_PREFIX + '/1/0/2/0/0/0/'),
    'physical': dict(labels=('爆发力', '弹跳', '灵活', '耐力', '平衡', '强壮', '速度', '体质'), title='身体', title_path=COMMON_PREFIX + '/2/0/0/0', row_prefix=COMMON_PREFIX + '/2/0/0/2/0/0/0/'),
}
LIMITATIONS = [
    '仅为本次 UI 采样内的属性显示标签与数值配对，不是原生球员实体或完整属性表。',
    '球员身份未知；不得用其他帧的姓名、导航文本、历史或记忆绑定，不提供个体建议。',
    '类别只保留显示分组，不证明球员位置；未读取或不成对的行均未知，不补值、不填零。',
    '可见性、遮挡和当前页面身份未经独立验证，可能包含隐藏或缓存文本。',
]


def _text(value):
    _require(isinstance(value, str) and 0 < len(value) <= 1024, 'invalid_attribute_text')
    return value.replace('\u200b', '')  # No trimming, markup removal or other Unicode normalization.


def project_validated_current_page_attributes(texts, *, game, source, provenance, capture_text_sha256):
    result = dict(status='unavailable', reason='unsupported_layout', profile_id=PROFILE_ID,
                  experimental=True, source='ui', partial=True, production_ready=False,
                  identity=None, business_identity_known=False, individual_advice_allowed=False,
                  missing_rows_unknown=True, groups=[], limitations=list(LIMITATIONS), projection_sha256=None)
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
        groups = []
        seen_labels = set()
        for key, category in CATEGORIES.items():
            title_path, prefix = category['title_path'], category['row_prefix']
            _require(title_path in paths and _text(paths[title_path]) == category['title'], 'unsupported_category_or_locale')
            indices = set()
            for path in paths:
                if path.startswith(prefix):
                    index, separator, _ = path[len(prefix):].partition('/')
                    _require(separator and re.fullmatch(r'0|[1-9][0-9]?', index)
                             and int(index) < 32, 'unsupported_attribute_row')
                    indices.add(int(index))
            rows = []
            for index in sorted(indices):
                refs = dict(label_display=prefix + str(index) + LABEL_SUFFIX,
                            value=prefix + str(index) + VALUE_SUFFIX)
                label = _text(paths[refs['label_display']]) if refs['label_display'] in paths else None
                value = _text(paths[refs['value']]) if refs['value'] in paths else None
                if label is not None:
                    _require(label in category['labels'], 'invalid_attribute_label')
                    _require(label not in seen_labels, 'duplicate_attribute_label')
                    seen_labels.add(label)
                if value is not None:
                    _require(re.fullmatch(r'[1-9]|1[0-9]|20', value) is not None, 'invalid_attribute_value')
                if label is None or value is None:
                    continue  # No pairing with adjacent rows and no fabricated missing values.
                field_provenance = {
                    field: {**provenance, 'ui_path': path, 'category_title_path': title_path,
                            'profile_id': PROFILE_ID, 'game_build': GAME_BUILD,
                            'adapter_version': source['adapter_version'],
                            'capture_text_sha256': capture_text_sha256}
                    for field, path in refs.items()
                }
                rows.append(dict(row_index=index, label_display=label, value_display=value, value=int(value),
                                 field_provenance=field_provenance,
                                 raw_texts={field: paths[path] for field, path in refs.items()}))
            groups.append(dict(category_key=key, category_display=category['title'], rows=rows,
                               rows_complete=False, title_provenance={**provenance, 'ui_path': title_path},
                               raw_title=paths[title_path]))
        _require(any(group['rows'] for group in groups), 'no_complete_attribute_rows')
        fingerprint = hashlib.sha256(json.dumps(dict(profile=PROFILE_ID, game=game, source=source,
                    capture_text_sha256=capture_text_sha256), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        result.update(status='experimental_ui_current_page_attributes', reason='matched_pinned_layout',
                      groups=groups, projection_sha256=fingerprint)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        reason = str(error)
        result['reason'] = reason if re.fullmatch(r'[a-z_]{1,40}', reason) else 'invalid_attribute_capture'
    return result
