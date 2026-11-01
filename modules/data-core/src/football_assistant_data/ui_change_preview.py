"""Model-free, capture-local display fingerprints for conservative desktop notices.

Fingerprints describe UI display contents only, never a football event, player
identity, or stable page identity. No source text or paths leave this projection.
"""
import hashlib
import json

from .schedule_projection import project_validated_schedule
from .next_match_projection import project_validated_next_match, DISPLAY_FIELDS as NEXT_FIELDS
from .tactics_projection import project_validated_tactics
from .current_page_attributes_projection import project_validated_current_page_attributes


def unavailable_ui_change_preview():
    return dict(status='unavailable', source='ui', synthetic=False, partial=True, production_ready=False)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def project_validated_ui_change_preview(texts, *, game, source, provenance, capture_text_sha256):
    """Called only with one complete capture accepted by the common UI gate."""
    arguments = dict(game=game, source=source, provenance=provenance,
                     capture_text_sha256=capture_text_sha256)
    matches = []
    schedule = project_validated_schedule(texts, **arguments)
    if schedule['status'] == 'experimental_ui_schedule':
        keys = ('date_display', 'opponent_display', 'home_away_display', 'competition_display')
        # A row's capture coordinate and a display-only row reorder are not changes.
        rows = sorted(tuple(row[key] for key in keys) for row in schedule['rows'])
        matches.append(('schedule', schedule['profile_id'], rows))
    next_match = project_validated_next_match(texts, **arguments)
    if next_match['status'] == 'experimental_ui_next_match':
        matches.append(('next_match', next_match['profile_id'], {key: next_match[key] for key in NEXT_FIELDS}))
    tactics = project_validated_tactics(texts, **arguments)
    if tactics['status'] == 'experimental_ui_tactics':
        display = {key: tactics[key] for key in ('formation_display', 'style_display', 'mentality_display')}
        matches.append(('tactics', tactics['profile_id'], display))
    attributes = project_validated_current_page_attributes(texts, **arguments)
    if (attributes['status'] == 'experimental_ui_current_page_attributes'
            and attributes.get('identity') is None and attributes.get('individual_advice_allowed') is False):
        display = sorted((group['category_display'], sorted(
            (row['label_display'], row['value']) for row in group['rows'])) for group in attributes['groups'])
        matches.append(('current_page_attributes', attributes['profile_id'], display))
    if len(matches) != 1:
        return unavailable_ui_change_preview()
    kind, profile, display = matches[0]
    # Deliberate output whitelist: neither raw UI nor field provenance nor values
    # are needed by the notice loop. Session/event/time fence freshness locally.
    return dict(status='ready', kind=kind, source='ui', synthetic=False, partial=True,
                production_ready=False, session_id=provenance['session_id'],
                event_id=provenance['event_id'], captured_at=provenance['captured_at'],
                display_sha256=_digest(display), scope_sha256=_digest(dict(
                    kind=kind, profile=profile, path_scope=provenance['path_scope'],
                    focus_root_path=provenance['focus_root_path'])))
