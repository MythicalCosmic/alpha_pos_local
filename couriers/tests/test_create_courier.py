"""Courier provisioning and mobile-auth security contract tests."""
import json
import secrets
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

pytestmark = pytest.mark.django_db

ROOT = '/api/couriers/'
CREATE = '/api/couriers/create'


def _staff_token(role='MANAGER'):
    from base.models import Session, User
    from base.repositories.session import SessionRepository

    user = User.objects.create(
        email=f'{role.lower()}@x.local',
        first_name=role.title(),
        last_name='User',
        role=role,
        status='ACTIVE',
        password='!',
    )
    token = secrets.token_hex(32)
    Session.objects.create(
        user_id=user,
        ip_address='127.0.0.1',
        payload=SessionRepository.hash_token(token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return token


def _post(path, body, token=None):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
    return Client().post(
        path,
        data=json.dumps(body),
        content_type='application/json',
        **headers,
    )


def test_create_returns_one_time_opaque_claim_and_session_expiry():
    from base.models import Session
    from base.repositories.session import SessionRepository
    from couriers.models import Courier, CourierLoginClaim, CourierRefreshToken
    from couriers.tokens import QR_CLAIM_PREFIX, _digest

    manager = _staff_token()
    response = _post(
        CREATE,
        {
            'first_name': 'Ali',
            'last_name': 'Valiyev',
            'phone': '+998901112233',
            'password': 'kuryer123',
        },
        manager,
    )
    assert response.status_code == 200, response.content
    data = response.json()['data']
    assert data['courier']['phone'] == '+998901112233'
    assert data['courier']['id'].startswith('CR-')
    assert 'password' not in data
    assert data['qr']['v'] == 2
    assert data['qr']['token'].startswith(QR_CLAIM_PREFIX)
    assert data['qr']['expires_at'] == data['expires_at']
    assert '+998901112233' not in data['qr']['token']
    assert 'kuryer123' not in json.dumps(data)
    assert Courier.objects.filter(phone='+998901112233').exists()

    claim = CourierLoginClaim.objects.get()
    assert claim.token_digest == _digest(data['qr']['token'])
    assert data['qr']['token'] not in claim.token_digest

    login = _post('/auth/courier/login/', {'qr': data['qr']['token']})
    assert login.status_code == 200, login.content
    auth = login.json()
    assert auth['token']
    assert auth['token_type'] == 'Token'
    assert auth['expires_at']
    assert auth['refresh_token']
    assert auth['refresh_expires_at']

    refresh_row = CourierRefreshToken.objects.get()
    assert refresh_row.token_digest == _digest(auth['refresh_token'])
    assert auth['refresh_token'] not in refresh_row.token_digest
    assert not Session.objects.filter(payload=auth['token']).exists()
    assert Session.objects.filter(
        payload=SessionRepository.hash_token(auth['token']),
    ).exists()

    replay = _post('/auth/courier/login/', {'qr': data['qr']['token']})
    assert replay.status_code == 401
    assert replay.json()['message'] == 'Invalid or expired login QR'


def test_omitted_password_is_never_generated_into_response_or_qr():
    manager = _staff_token()
    response = _post(
        CREATE,
        {'first_name': 'Bek', 'phone': '+998905550000'},
        manager,
    )
    assert response.status_code == 200, response.content
    data = response.json()['data']
    assert 'password' not in data
    assert ':' not in data['qr']['token']
    assert _post('/auth/courier/login/', {
        'qr': data['qr']['token'],
    }).status_code == 200


def test_create_and_regenerate_remain_manager_only():
    cashier = _staff_token('CASHIER')
    create = _post(CREATE, {'phone': '+998900000001'}, cashier)
    assert create.status_code == 403

    manager = _staff_token()
    courier = _post(
        CREATE, {'phone': '+998900000002'}, manager,
    ).json()['data']
    regenerate = _post(
        f"/api/couriers/{courier['id']}/regenerate", {}, cashier,
    )
    assert regenerate.status_code == 403


def test_create_requires_auth_and_duplicate_phone_conflicts():
    assert _post(CREATE, {'phone': '+998900000003'}).status_code in (401, 403)

    manager = _staff_token()
    body = {'phone': '+998905556677'}
    assert _post(CREATE, body, manager).status_code == 200
    assert _post(CREATE, body, manager).status_code == 409


def test_short_manual_password_is_rejected():
    manager = _staff_token()
    response = _post(
        CREATE,
        {'phone': '+998901234567', 'password': 'ab'},
        manager,
    )
    assert response.status_code == 400


def test_regenerate_rotates_claim_without_changing_manual_password():
    manager = _staff_token()
    created = _post(
        CREATE,
        {'phone': '+998909990000', 'password': 'first123'},
        manager,
    ).json()['data']
    old_claim = created['qr']['token']

    rotated = _post(
        f"/api/couriers/{created['id']}/regenerate", {}, manager,
    )
    assert rotated.status_code == 200, rotated.content
    data = rotated.json()['data']
    assert data['qr']['token'] != old_claim
    assert 'password' not in data
    assert _post('/auth/courier/login/', {'qr': old_claim}).status_code == 401
    assert _post('/auth/courier/login/', {
        'qr': data['qr']['token'],
    }).status_code == 200
    assert _post('/auth/courier/login/', {
        'phone': '+998909990000',
        'password': 'first123',
    }).status_code == 200


def test_expired_qr_claim_is_rejected():
    from couriers.models import CourierLoginClaim

    manager = _staff_token()
    created = _post(
        CREATE, {'phone': '+998901010101'}, manager,
    ).json()['data']
    CourierLoginClaim.objects.update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    response = _post('/auth/courier/login/', {'qr': created['qr']['token']})
    assert response.status_code == 401
    assert response.json()['message'] == 'Invalid or expired login QR'


def test_password_login_returns_access_and_refresh_expiry():
    manager = _staff_token()
    _post(
        CREATE,
        {'phone': '+998902020202', 'password': 'manual-secret'},
        manager,
    )
    response = _post('/auth/courier/login/', {
        'phone': '+998902020202',
        'password': 'manual-secret',
    })
    assert response.status_code == 200
    body = response.json()
    assert {
        'token', 'expires_at', 'refresh_token', 'refresh_expires_at',
    }.issubset(body)
    assert 'manual-secret' not in json.dumps(body)


def test_refresh_rotation_and_replay_revoke_whole_family():
    from base.models import Session
    from base.repositories.session import SessionRepository
    from couriers.models import CourierRefreshToken

    manager = _staff_token()
    created = _post(
        CREATE, {'phone': '+998903030303'}, manager,
    ).json()['data']
    auth = _post(
        '/auth/courier/login/', {'qr': created['qr']['token']},
    ).json()

    refreshed = _post('/auth/courier/refresh/', {
        'refresh_token': auth['refresh_token'],
    })
    assert refreshed.status_code == 200, refreshed.content
    replacement = refreshed.json()
    assert replacement['token'] != auth['token']
    assert replacement['refresh_token'] != auth['refresh_token']
    assert not Session.objects.filter(
        payload=SessionRepository.hash_token(auth['token']),
    ).exists()
    assert Client().get(
        '/courier/me/',
        HTTP_AUTHORIZATION=f"Token {replacement['token']}",
    ).status_code == 200

    replay = _post('/auth/courier/refresh/', {
        'refresh_token': auth['refresh_token'],
    })
    assert replay.status_code == 401
    assert Client().get(
        '/courier/me/',
        HTTP_AUTHORIZATION=f"Token {replacement['token']}",
    ).status_code == 401
    assert CourierRefreshToken.objects.filter(
        revoked_at__isnull=True,
    ).count() == 0


def test_expired_refresh_is_rejected():
    from couriers.models import CourierRefreshToken

    manager = _staff_token()
    created = _post(
        CREATE, {'phone': '+998904040404'}, manager,
    ).json()['data']
    auth = _post(
        '/auth/courier/login/', {'qr': created['qr']['token']},
    ).json()
    CourierRefreshToken.objects.update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    response = _post('/auth/courier/refresh/', {
        'refresh_token': auth['refresh_token'],
    })
    assert response.status_code == 401


def test_revoke_by_refresh_token_is_family_wide_and_idempotent():
    manager = _staff_token()
    created = _post(
        CREATE, {'phone': '+998905050505'}, manager,
    ).json()['data']
    auth = _post(
        '/auth/courier/login/', {'qr': created['qr']['token']},
    ).json()

    revoked = _post('/auth/courier/revoke/', {
        'refresh_token': auth['refresh_token'],
    })
    assert revoked.status_code == 200
    assert revoked.json() == {'ok': True}
    assert Client().get(
        '/courier/me/',
        HTTP_AUTHORIZATION=f"Token {auth['token']}",
    ).status_code == 401
    assert _post('/auth/courier/refresh/', {
        'refresh_token': auth['refresh_token'],
    }).status_code == 401
    assert _post('/auth/courier/revoke/', {
        'refresh_token': auth['refresh_token'],
    }).status_code == 200


def test_logout_revokes_refresh_family():
    manager = _staff_token()
    created = _post(
        CREATE, {'phone': '+998906060606'}, manager,
    ).json()['data']
    auth = _post(
        '/auth/courier/login/', {'qr': created['qr']['token']},
    ).json()
    logout = _post('/auth/courier/logout/', {}, auth['token'])
    assert logout.status_code == 200
    assert _post('/auth/courier/refresh/', {
        'refresh_token': auth['refresh_token'],
    }).status_code == 401


def test_password_reset_revokes_sessions_without_echoing_password():
    manager = _staff_token()
    created = _post(
        CREATE,
        {'phone': '+998907070707', 'password': 'first-secret'},
        manager,
    ).json()['data']
    auth = _post('/auth/courier/login/', {
        'phone': '+998907070707',
        'password': 'first-secret',
    }).json()

    response = _post(
        f"/api/couriers/{created['id']}/regenerate",
        {'password': 'second-secret'},
        manager,
    )
    assert response.status_code == 200
    assert 'second-secret' not in json.dumps(response.json())
    assert Client().get(
        '/courier/me/',
        HTTP_AUTHORIZATION=f"Token {auth['token']}",
    ).status_code == 401
    assert _post('/auth/courier/refresh/', {
        'refresh_token': auth['refresh_token'],
    }).status_code == 401
    assert _post('/auth/courier/login/', {
        'phone': '+998907070707',
        'password': 'first-secret',
    }).status_code == 401
    assert _post('/auth/courier/login/', {
        'phone': '+998907070707',
        'password': 'second-secret',
    }).status_code == 200
