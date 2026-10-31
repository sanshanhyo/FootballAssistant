"""Validate traversal scope only; never interpret diagnostics as football facts."""
import json
import re


def _fail():
    raise ValueError('invalid_ui_capture_scope')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _path(value, *, relative=False):
    if not isinstance(value, str) or len(value) > 128:
        return False
    pattern = r'focus(?:/(?:0|[1-9][0-9]{0,2}))*' if relative else r'panel(?:0|[1-9][0-9]?)(?:/(?:0|[1-9][0-9]{0,2}))*'
    if not re.fullmatch(pattern, value):
        return False
    parts = value.split('/')
    return (relative or int(parts[0][5:]) <= 31) and all(int(p) <= 511 for p in parts[1:])


def capture_path_scope(diagnostics):
    """Absent old metadata defaults to normal absolute paths; malformed metadata fails closed."""
    captures = [d for d in diagnostics if d.get('entity_id') == 'diagnostic/capture']
    default = dict(path_scope='panel_absolute', focus_root_path=None, identity_scope='capture_local_ui_path')
    if not captures:
        return default
    if len(captures) != 1:
        _fail()
    value = captures[0].get('value')
    if not isinstance(value, str) or not 0 < len(value) <= 4000:
        _fail()
    try:
        metrics = json.loads(value, object_pairs_hook=_object, parse_constant=lambda _: _fail())
    except (ValueError, TypeError, RecursionError):
        _fail()
    if not isinstance(metrics, dict):
        _fail()
    scope = metrics.get('path_scope', 'panel_absolute')
    requested, resolved = metrics.get('focus_requested', False), metrics.get('focus_resolved', False)
    root = metrics.get('focus_root_path')
    if (scope not in ('panel_absolute', 'focus_relative') or type(requested) is not bool
            or type(resolved) is not bool or metrics.get('identity_scope', 'capture_local_ui_path') != 'capture_local_ui_path'):
        _fail()
    if requested:
        if not resolved or not _path(root):
            _fail()
    elif resolved or root is not None or scope != 'panel_absolute':
        _fail()
    return dict(path_scope=scope, focus_root_path=root, identity_scope='capture_local_ui_path')


def validate_evidence_path_scope(path, scope):
    if scope['path_scope'] == 'focus_relative':
        if not _path(path, relative=True):
            _fail()
    elif path == 'focus' or path.startswith('focus/'):
        _fail()
