"""One explicitly approved normal-user finite capture acceptance. Stdlib only.

No impersonation, credentials, model calls, rearming, cleanup of prior captures,
or game launch/navigation. Source files never choose their own trusted identity.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import UUID, uuid4

from .windows_capture_files import _components
from .windows_finite_files import _object, WindowsProducerLifetime
from .windows_acceptance_security import AcceptanceFiles

APP_COMMIT = 'df6f95359eaaede7fcc2220b1508ff25d6eb290e'
PORTABLE_SHA256 = '0738bd59fb184418a84003aa00e64d9f1415927b303e7a544a85de9964236d63'
GAME_SHA256 = '820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a'
APPROVED_PARENT = r'D:\FootballAssistant-Tests\20261031-bridge-prep'
SOURCE_KEYS = ('pid', 'entry_tid', 'session_id', 'bridge_sha256', 'game_sha256')
PLAN_KEYS = {'schema_version', 'app_commit', 'candidate_dir', 'portable_exe', 'portable_sha256',
             'bridge_sha256', 'game_sha256', 'pid', 'entry_tid', 'session_id', 'user_data_name'}
MAX_RESPONSE = 262144


def require(condition, code):
    if not condition:
        raise ValueError(code)


def utc(value):
    require(isinstance(value, str) and len(value) <= 40, 'invalid_utc')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), 'invalid_utc')
    return parsed


def validate_plan(raw, expected_digest):
    require(isinstance(expected_digest, str) and re.fullmatch('[0-9a-f]{64}', expected_digest), 'invalid_plan_digest')
    require(isinstance(raw, bytes) and len(raw) <= 8192 and hashlib.sha256(raw).hexdigest() == expected_digest, 'plan_digest_mismatch')
    plan = _object(raw)
    require(set(plan) == PLAN_KEYS and type(plan['schema_version']) is int and plan['schema_version'] == 1, 'invalid_plan_fields')
    require(plan['app_commit'] == APP_COMMIT and plan['portable_sha256'] == PORTABLE_SHA256, 'unapproved_app_artifact')
    require(plan['game_sha256'] == GAME_SHA256, 'unapproved_game_build')
    require(isinstance(plan['bridge_sha256'], str) and re.fullmatch('[0-9a-f]{64}', plan['bridge_sha256']), 'invalid_bridge_hash')
    for key in ('pid', 'entry_tid'):
        require(type(plan[key]) is int and 0 < plan[key] <= 0xffffffff, 'invalid_source_identity')
    require(isinstance(plan['session_id'], str) and str(UUID(plan['session_id'])) == plan['session_id'] and UUID(plan['session_id']).int != 0, 'invalid_session')
    for key in ('candidate_dir', 'portable_exe'):
        require(isinstance(plan[key], str), 'invalid_local_path')
        _components(plan[key])
    require(ntpath.normcase(ntpath.dirname(plan['candidate_dir'])) == ntpath.normcase(APPROVED_PARENT), 'candidate_outside_approved_parent')
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}', ntpath.basename(plan['candidate_dir'])), 'invalid_candidate_name')
    require(plan['portable_exe'].lower().endswith('.exe'), 'invalid_portable_path')
    require(isinstance(plan['user_data_name'], str) and re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', plan['user_data_name']), 'invalid_user_data_name')
    return plan


def validate_source(plan, session, module, state):
    for record in (session, module, state):
        require(isinstance(record, dict), 'invalid_control_object')
        for key in SOURCE_KEYS:
            if key == 'entry_tid' and record is not session:
                continue
            require(type(record.get(key)) is type(plan[key]) and record[key] == plan[key], 'trusted_source_mismatch')
    require(session.get('schema_version') == 4 and session.get('mode') == 'goalkeeper_rows0_3'
            and session.get('window_class') == 'UnityWndClass'
            and session.get('finite_rows_enabled_by_default') is False
            and session.get('raw_diagnostics_only') is True
            and isinstance(session.get('allowed_scopes'), list) and 'profile_all_rows' in session['allowed_scopes'], 'unsupported_source_scope')
    require(module.get('state') == 'ready', 'module_not_ready')
    require(state.get('consumed') is False and state.get('terminal') is False
            and state.get('outcome') == 'running' and state.get('batch_id') is None, 'fresh_session_required')


def make_request(plan, now, new_uuid=uuid4):
    request = dict(schema_version=4, mode='profile_all_rows', batch_id=str(new_uuid()), page_epoch=str(new_uuid()),
                   first_nonce=str(new_uuid()), second_nonce=str(new_uuid()), pid=plan['pid'], session_id=plan['session_id'],
                   bridge_sha256=plan['bridge_sha256'], game_sha256=plan['game_sha256'], window_class='UnityWndClass',
                   stable_profile_asserted=True, requested_at=now.isoformat(), expires_at=(now+timedelta(seconds=120)).isoformat())
    require(len({request[key] for key in ('batch_id', 'page_epoch', 'first_nonce', 'second_nonce')}) == 4, 'duplicate_request_uuid')
    registration = {key: plan[key] for key in SOURCE_KEYS}
    registration.update({key: request[key] for key in ('batch_id', 'page_epoch', 'first_nonce', 'second_nonce', 'expires_at', 'window_class')})
    registration['manifest_name'] = request['mode']
    return request, registration


def launch_environment(environ, user_data, registration):
    # No inherited secrets, model settings, external runtime, proxy or dotenv path.
    allowed = {'PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'APPDATA',
               'LOCALAPPDATA', 'USERPROFILE', 'ALLUSERSPROFILE', 'PROGRAMDATA', 'PATHEXT', 'HOMEDRIVE', 'HOMEPATH'}
    result = {key: value for key, value in environ.items() if key in allowed}
    result['FA_COMPANION_USER_DATA_DIR'] = str(user_data)
    result['FOOTBALL_ASSISTANT_WINDOWS_FINITE_REGISTRATION'] = json.dumps(registration, separators=(',', ':'))
    result['FOOTBALL_ASSISTANT_MODEL_REQUEST_LIMIT'] = '1'
    return result


def validate_runtime(runtime):
    require(isinstance(runtime, dict) and runtime.get('base_url') == 'http://127.0.0.1:17827', 'unexpected_runtime_address')
    require(isinstance(runtime.get('token'), str) and 16 <= len(runtime['token']) <= 256, 'invalid_runtime_token')
    require(type(runtime.get('pid')) is int and runtime['pid'] > 0, 'invalid_runtime_pid')
    utc(runtime.get('started_at'))
    return runtime


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('local_api_redirect_refused')


def get_local(runtime, endpoint, timeout=2):
    validate_runtime(runtime)
    require(endpoint in ('/v1/status', '/v1/reader/current-page-attributes'), 'unsupported_acceptance_endpoint')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(runtime['base_url']+endpoint, headers={'Authorization': 'Bearer '+runtime['token'], 'Accept': 'application/json'})
    with opener.open(request, timeout=timeout) as response:
        require(response.status == 200, 'local_api_failed')
        raw = response.read(MAX_RESPONSE+1)
        require(len(raw) <= MAX_RESPONSE, 'oversize_api_response')
        return _object(raw)


def summarize(envelope, plan, request, now):
    require(isinstance(envelope, dict), 'invalid_api_envelope')
    if envelope.get('status') == 'unavailable':
        return None
    provenance = envelope.get('provenance') or {}
    projection = envelope.get('current_page_attributes') or {}
    require(envelope.get('status') == 'experimental_ui_current_page_attributes'
            and envelope.get('source') == 'ui' and envelope.get('identity') is None
            and envelope.get('business_identity_known') is False and envelope.get('production_ready') is False, 'invalid_api_semantics')
    require(provenance.get('platform') == 'windows-x64' and provenance.get('adapter_id') == 'footballassistant.windows-finite-ui'
            and provenance.get('session_id') == plan['session_id'] and provenance.get('expires_at') == request['expires_at'], 'api_source_mismatch')
    require(projection.get('batch_id') == request['batch_id'] and projection.get('snapshot_atomic') is False
            and projection.get('business_identity_known') is False and projection.get('identity') is None
            and projection.get('retention') == 'approved_finite_capture_summary', 'invalid_batch_summary')
    progress = projection.get('progress') or {}
    require(type(progress.get('chunks_received')) is int and 0 < progress['chunks_received'] <= 18
            and progress.get('chunks_expected') == 18 and progress.get('rows_expected') == 35, 'invalid_progress')
    groups = projection.get('groups')
    require(isinstance(groups, list) and 0 < len(groups) <= 3, 'invalid_groups')
    expected_counts = {'goalkeeper': 13, 'mental': 14, 'physical': 8}
    total = 0; stale = 0; starts = []; ends = []; seen_groups = set()
    for group in groups:
        key = group.get('category_key')
        require(key in expected_counts and key not in seen_groups, 'invalid_category')
        seen_groups.add(key)
        rows = group.get('rows')
        require(isinstance(rows, list) and 0 < len(rows) <= expected_counts[key], 'invalid_rows')
        seen_indices = set(); seen_labels = set()
        for row in rows:
            require(type(row.get('row_index')) is int and 0 <= row['row_index'] < expected_counts[key]
                    and row['row_index'] not in seen_indices and type(row.get('value')) is int and 1 <= row['value'] <= 20, 'invalid_row')
            require(isinstance(row.get('label_display'), str) and row['label_display'] not in seen_labels, 'invalid_row_label')
            seen_indices.add(row['row_index']); seen_labels.add(row['label_display'])
            field = row.get('field_provenance') or {}
            start, finish = utc(field.get('capture_started_at')), utc(field.get('capture_finished_at'))
            require(utc(request['requested_at']) <= start <= finish <= now <= utc(request['expires_at']), 'invalid_capture_interval')
            require(field.get('association') == 'same_row_same_chunk' and field.get('player_identity') is None, 'invalid_row_identity')
            expected_freshness = 'fresh' if (now-start).total_seconds() <= 10 else 'stale'
            # Time can cross the 10s boundary while the response is transported.
            require(row.get('capture_freshness') in ('fresh', 'stale'), 'invalid_row_freshness')
            stale += expected_freshness == 'stale'
            starts.append(start); ends.append(finish); total += 1
    require(progress.get('rows_received') == total and total <= 35, 'row_count_mismatch')
    complete = progress.get('complete') is True
    require(not complete or (progress['chunks_received'] == 18 and total == 35 and seen_groups == set(expected_counts)), 'incomplete_final_summary')
    return dict(chunks_received=progress['chunks_received'], rows_received=total, complete=complete,
                capture_started_at=min(starts).isoformat(), capture_finished_at=max(ends).isoformat(), stale_rows=stale,
                source_binding_verified=True, player_identity_known=False, snapshot_atomic=False)


def controls(files, root, private):
    return tuple(files.read_control(root, name, private=private) for name in ('session.json', 'module-status.json', 'finite-rows-state.json'))


def ensure_port_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(('127.0.0.1', 17827))
        except OSError:
            raise ValueError('local_port_already_in_use') from None


def execute(plan, files, *, approved_acl, approved_capture, stable_profile, execute_actions=False,
            now=lambda: datetime.now(timezone.utc), monotonic=time.monotonic, sleep=time.sleep,
            spawn=subprocess.Popen, fetch=get_local, lifetime_factory=WindowsProducerLifetime, emit=lambda value: None):
    result = dict(status='not_started', stage='preflight', automatic_model_calls=0, ai_answer_verified=False,
                  pet_ui_attributes_verified=False, acl_change_attempted=False, acl_changed=False, capture_requested=False, pet_started=False)
    lifetime = None
    try:
        files.verify_user()  # Must precede all capture/userData mutations, even with supplied approvals.
        root = Path(ntpath.join(plan['candidate_dir'], 'windows-finite-rows-private'))
        bridge = Path(ntpath.join(plan['candidate_dir'], 'FootballAssistant.WindowsFiniteRowsCandidate.dll'))
        require(files.hash_local_file(bridge, 64*1024*1024) == plan['bridge_sha256'], 'bridge_file_hash_mismatch')
        require(files.hash_local_file(Path(plan['portable_exe']), 2*1024*1024*1024) == PORTABLE_SHA256, 'portable_hash_mismatch')
        validate_source(plan, *controls(files, root, private=False))
        files.assert_unused(root)
        lifetime = lifetime_factory(plan['pid'], plan['entry_tid'], 'UnityWndClass')
        require(lifetime.alive(), 'producer_lifetime_unavailable')
        ensure_port_free()
        if not execute_actions:
            return {**result, 'status': 'preflight_passed', 'approval_required': True}
        require(approved_acl and approved_capture and stable_profile, 'explicit_approval_required')
        result['stage'] = 'protect_approved_scope'
        result['acl_change_attempted'] = True
        files.harden_capture(root); result['acl_changed'] = True
        validate_source(plan, *controls(files, root, private=True)); files.assert_unused(root)
        user_data = files.create_user_data(plan['user_data_name'])
        portable = files.stage_portable(Path(plan['portable_exe']), user_data, PORTABLE_SHA256)
        settings = dict(version=1, backend=dict(port=17827), bridgePrivateRoot=str(root), backendEnvFile='')
        files.write_new(user_data, 'settings.json', json.dumps(settings, separators=(',', ':')).encode())
        result['stage'] = 'publish_one_finite_request'
        require(lifetime.alive(), 'producer_lifetime_unavailable')
        validate_source(plan, *controls(files, root, private=True)); files.assert_unused(root)
        request, registration = make_request(plan, now())
        files.write_new(root, 'finite-rows-request.json', json.dumps(request, separators=(',', ':')).encode())
        result['capture_requested'] = True
        # Never republish, regenerate nonces, delete old requests or retry this action.
        result['stage'] = 'launch_verified_pet'
        process = spawn([str(portable)], cwd=str(user_data), env=launch_environment(os.environ, user_data, registration),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result['pet_started'] = True
        result['stage'] = 'await_authenticated_capture'
        end_tick = monotonic()+120
        runtime = None; summary = None; last_progress = None
        while monotonic() < end_tick and now() < utc(request['expires_at']):
            require(lifetime.alive(), 'producer_lifetime_lost')
            try:
                current_runtime = validate_runtime(files.read_runtime(user_data))
                require(runtime is None or current_runtime == runtime, 'runtime_replaced')
                runtime = current_runtime
                status = fetch(runtime, '/v1/status')
                require(status.get('modelConfigured') is False, 'unexpected_model_configuration')
                current = summarize(fetch(runtime, '/v1/reader/current-page-attributes'), plan, request, now())
                if current:
                    progress = (current['chunks_received'], current['rows_received'])
                    if progress != last_progress:
                        emit(dict(status='capturing', chunks_received=progress[0], rows_received=progress[1])); last_progress=progress
                    if current['complete']:
                        summary=current; break
            except urllib.error.HTTPError:
                raise ValueError('local_api_http_failure') from None
            except (FileNotFoundError, ConnectionError, TimeoutError, urllib.error.URLError):
                pass  # Bounded startup/polling only; never repeat capture or refresh old timestamps.
            sleep(0.5)
        require(summary is not None and runtime is not None, 'capture_not_verified_before_expiry')
        result.update(summary, status='api_capture_complete', model_configured=False, pet_launch_process_alive=process.poll() is None,
                      app_artifact_verified=True, app_commit=APP_COMMIT, expires_at=request['expires_at'])
        result['stage'] = 'verify_expiry_clear'
        # Natural expiry only: no game navigation, kill, rearm, model request or synthetic invalidation.
        while now() <= utc(request['expires_at']) and monotonic() < end_tick+3:
            require(lifetime.alive(), 'producer_lifetime_lost')
            sleep(0.5)
        require(monotonic() <= end_tick+5, 'expiry_check_window_ended')
        require(validate_runtime(files.read_runtime(user_data)) == runtime, 'runtime_replaced')
        expired = fetch(runtime, '/v1/reader/current-page-attributes')
        require(expired.get('status') == 'unavailable' and expired.get('current_page_attributes') is None, 'expiry_clear_not_verified')
        result.update(stage='complete', status='api_capture_and_expiry_verified', expiry_clear_verified=True)
        return result
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,80}', str(error)) else 'acceptance_operation_failed'
        return {**result, 'status': 'failed', 'code': code, 'winerror': getattr(error, 'winerror', None)}
    finally:
        if lifetime is not None:
            lifetime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approve-private-acl', action='store_true')
    parser.add_argument('--approve-finite-capture', action='store_true')
    parser.add_argument('--stable-profile-asserted', action='store_true')
    args = parser.parse_args(argv)
    try:
        files = AcceptanceFiles(); files.verify_user()
        plan = validate_plan(files.read_plan(Path(args.plan)), args.plan_sha256)
        result = execute(plan, files, approved_acl=args.approve_private_acl, approved_capture=args.approve_finite_capture,
                         stable_profile=args.stable_profile_asserted, execute_actions=args.execute,
                         emit=lambda value: print(json.dumps(value, separators=(',', ':')), flush=True))
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,80}', str(error)) else 'preflight_failed'
        result = dict(status='failed', stage='preflight', code=code, automatic_model_calls=0, ai_answer_verified=False)
    print(json.dumps(result, separators=(',', ':')), flush=True)
    return 0 if result['status'] in ('preflight_passed', 'api_capture_and_expiry_verified') else 2


if __name__ == '__main__':
    sys.exit(main())
