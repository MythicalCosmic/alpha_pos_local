"""Net-new POST /api/couriers/create provisioning + login-QR round-trip (local)."""
import json
import secrets
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _staff_token():
    from base.models import User, Session
    from base.repositories.session import SessionRepository
    u = User.objects.create(email='mgr@x.local', first_name='M', last_name='gr',
                            role='MANAGER', status='ACTIVE', password='!')
    tok = secrets.token_hex(32)
    Session.objects.create(user_id=u, ip_address='127.0.0.1',
                           payload=SessionRepository.hash_token(tok),
                           expires_at=timezone.now() + timedelta(hours=1))
    return tok


def test_create_courier_qr_then_login():
    from couriers.models import Courier
    staff = _staff_token()
    c = Client()
    r = c.post('/api/couriers/create',
               data=json.dumps({'first_name': 'Ali', 'last_name': 'Valiyev',
                                'phone': '+998901112233'}),
               content_type='application/json',
               HTTP_AUTHORIZATION=f'Bearer {staff}')
    assert r.status_code == 200, r.content
    d = r.json()['data']
    assert d['courier']['phone'] == '+998901112233' and d['courier']['id'].startswith('CR-')
    assert d['qr']['token'] == f"+998901112233:{d['password']}"
    assert Courier.objects.filter(phone='+998901112233').exists()
    # the rider scans the QR -> the app logs in with {qr: token}
    login = c.post('/auth/courier/login/', data=json.dumps({'qr': d['qr']['token']}),
                   content_type='application/json')
    assert login.status_code == 200, login.content
    assert login.json().get('token')


def test_create_courier_requires_staff():
    c = Client()
    r = c.post('/api/couriers/create', data=json.dumps({'phone': '+998900000000'}),
               content_type='application/json')
    assert r.status_code in (401, 403)


def test_duplicate_phone_409():
    staff = _staff_token()
    c = Client()
    body = json.dumps({'phone': '+998905556677'})
    hdr = {'HTTP_AUTHORIZATION': f'Bearer {staff}'}
    assert c.post('/api/couriers/create', data=body, content_type='application/json', **hdr).status_code == 200
    assert c.post('/api/couriers/create', data=body, content_type='application/json', **hdr).status_code == 409


def test_regenerate_rotates_password():
    staff = _staff_token()
    c = Client()
    r = c.post('/api/couriers/create', data=json.dumps({'phone': '+998907778899'}),
               content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {staff}')
    pk, old_pw = r.json()['data']['courier']['pk'], r.json()['data']['password']
    r2 = c.post(f'/api/couriers/{pk}/regenerate', content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {staff}')
    assert r2.status_code == 200
    new_pw = r2.json()['data']['password']
    assert new_pw != old_pw
    assert c.post('/auth/courier/login/', data=json.dumps({'qr': f'+998907778899:{old_pw}'}),
                  content_type='application/json').status_code == 401
    assert c.post('/auth/courier/login/', data=json.dumps({'qr': f'+998907778899:{new_pw}'}),
                  content_type='application/json').status_code == 200
