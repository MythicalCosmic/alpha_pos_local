import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from base.models import Order, Shift, User
from base.security.hashing import hash_password


pytestmark = pytest.mark.django_db


def _staff(*, name, role, branch="cloud"):
    return User.objects.create(
        first_name=name,
        last_name="Tester",
        email=f"{name.lower()}@test.local",
        password=hash_password("1234"),
        role=role,
        status=User.UserStatus.ACTIVE,
        branch_id=branch,
    )


def _login(client, user):
    response = client.post(
        "/auth-login",
        data=json.dumps({"user_id": user.pk, "password": "1234"}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.json()


def _active_shift(cashier):
    return Shift.objects.create(
        user=cashier,
        status=Shift.Status.ACTIVE,
        start_time=timezone.now() - timedelta(hours=1),
        branch_id="branch1",
        device_id="pytest-terminal",
    )


@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_cloud_scoped_cashier_can_close_own_branch_shift(client):
    cashier = _staff(name="Cashier", role=User.RoleChoices.CASHIER)
    shift = _active_shift(cashier)
    _login(client, cashier)

    response = client.post(
        "/shifts/end",
        data=json.dumps({"counted": {}}),
        content_type="application/json",
    )

    assert response.status_code == 200, response.json()
    shift.refresh_from_db()
    assert shift.status == Shift.Status.ENDED
    assert shift.end_time is not None


@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_manager_can_close_selected_same_branch_shift(client):
    manager = _staff(name="Manager", role=User.RoleChoices.MANAGER)
    cashier = _staff(name="Cashier", role=User.RoleChoices.CASHIER)
    shift = _active_shift(cashier)
    _login(client, manager)

    response = client.post(
        f"/shifts/{shift.pk}/end",
        data=json.dumps({"notes": "Manager-assisted close", "counted": {}}),
        content_type="application/json",
    )

    assert response.status_code == 200, response.json()
    shift.refresh_from_db()
    assert shift.status == Shift.Status.ENDED
    assert shift.notes == "Manager-assisted close"


@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_cashier_cannot_close_another_cashiers_shift(client):
    actor = _staff(name="Actor", role=User.RoleChoices.CASHIER)
    owner = _staff(name="Owner", role=User.RoleChoices.CASHIER)
    shift = _active_shift(owner)
    _login(client, actor)

    response = client.post(
        f"/shifts/{shift.pk}/end",
        data="{}",
        content_type="application/json",
    )

    assert response.status_code == 403
    shift.refresh_from_db()
    assert shift.status == Shift.Status.ACTIVE
    assert shift.end_time is None


@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_manager_close_requires_explicit_tender_counts(client):
    manager = _staff(name="Manager", role=User.RoleChoices.MANAGER)
    cashier = _staff(name="Cashier", role=User.RoleChoices.CASHIER)
    shift = _active_shift(cashier)
    _login(client, manager)

    response = client.post(
        f"/shifts/{shift.pk}/end",
        data="{}",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "counted_required"
    shift.refresh_from_db()
    assert shift.status == Shift.Status.ACTIVE
    assert shift.end_time is None


@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_manager_close_still_refuses_unpaid_order(client):
    manager = _staff(name="Manager", role=User.RoleChoices.MANAGER)
    cashier = _staff(name="Cashier", role=User.RoleChoices.CASHIER)
    shift = _active_shift(cashier)
    Order.objects.create(
        user=cashier,
        cashier=cashier,
        status=Order.Status.PREPARING,
        is_paid=False,
        branch_id="branch1",
        subtotal="10.00",
        total_amount="10.00",
    )
    _login(client, manager)

    response = client.post(
        f"/shifts/{shift.pk}/end",
        data=json.dumps({"counted": {}}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "unpaid" in response.json()["message"].lower()
    shift.refresh_from_db()
    assert shift.status == Shift.Status.ACTIVE
    assert shift.end_time is None
