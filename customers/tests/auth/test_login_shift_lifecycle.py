import pytest
from django.utils import timezone

from base.models import Session, Shift, User
from base.security.hashing import hash_password
from customers.services.auth_service import AuthService


pytestmark = pytest.mark.django_db


def _login(user, password="cashierpass"):
    return AuthService.login(
        user_id=user.id,
        password=password,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )


def test_repeated_login_resumes_one_shift_without_moving_its_start(
    cashier_user,
):
    first, first_status = _login(cashier_user)
    first_shift = Shift.objects.get(user=cashier_user)
    first_start = first_shift.start_time

    second, second_status = _login(cashier_user)
    first_shift.refresh_from_db()

    assert first_status == 200, first
    assert second_status == 200, second
    assert first["data"]["active_shift"]["resumed"] is False
    assert second["data"]["active_shift"]["resumed"] is True
    assert second["data"]["active_shift"]["id"] == first_shift.id
    assert first_shift.start_time == first_start
    assert Shift.objects.filter(
        user=cashier_user,
        status=Shift.Status.ACTIVE,
        end_time__isnull=True,
    ).count() == 1


def test_manager_login_also_creates_and_resumes_a_shift():
    manager = User.objects.create(
        first_name="Manager",
        last_name="Tester",
        email="manager-shift@test.local",
        password=hash_password("managerpass"),
        role=User.RoleChoices.MANAGER,
        status=User.UserStatus.ACTIVE,
    )

    first, first_status = AuthService.login(
        user_id=manager.id,
        password="managerpass",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    second, second_status = AuthService.login(
        user_id=manager.id,
        password="managerpass",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert first_status == 200, first
    assert second_status == 200, second
    assert first["data"]["active_shift"]["device_id"] is None
    assert first["data"]["active_shift"]["resumed"] is False
    assert second["data"]["active_shift"]["resumed"] is True
    assert Shift.objects.filter(user=manager, status=Shift.Status.ACTIVE).count() == 1


def test_login_claims_blank_legacy_shift_for_authenticated_cashier(
    cashier_user,
):
    legacy = Shift.objects.create(
        user=cashier_user,
        start_time=timezone.now(),
        status=Shift.Status.ACTIVE,
        branch_id=cashier_user.branch_id,
        device_id="",
    )

    result, status = _login(cashier_user)

    legacy.refresh_from_db()
    assert status == 200, result
    assert result["data"]["active_shift"]["id"] == legacy.id
    assert result["data"]["active_shift"]["resumed"] is True
    assert legacy.device_id == "pytest-terminal"


def test_foreign_device_shift_rejects_login_without_creating_session(
    cashier_user,
):
    Shift.objects.create(
        user=cashier_user,
        start_time=timezone.now(),
        status=Shift.Status.ACTIVE,
        branch_id=cashier_user.branch_id,
        device_id="other-terminal",
    )

    result, status = _login(cashier_user)

    assert status == 400
    assert "not bound to this terminal" in result["message"]
    assert not Session.objects.filter(user_id=cashier_user).exists()


def test_bad_password_creates_neither_session_nor_shift(cashier_user):
    result, status = _login(cashier_user, password="wrong-password")

    assert status == 401
    assert result["success"] is False
    assert not Session.objects.filter(user_id=cashier_user).exists()
    assert not Shift.objects.filter(user=cashier_user).exists()


def test_each_shared_till_cashier_can_create_orders_immediately_after_login(
    cashier_user,
    other_cashier_user,
    product,
):
    from customers.services.order_service import CustomerOrderService

    first_login, first_login_status = _login(cashier_user)
    second_login, second_login_status = _login(other_cashier_user)

    assert first_login_status == 200, first_login
    assert second_login_status == 200, second_login

    for cashier in (cashier_user, other_cashier_user):
        result, status = CustomerOrderService.create_order(
            user_id=cashier.id,
            cashier_id=cashier.id,
            items=[{"product_id": product.id, "quantity": 1}],
        )
        assert status == 201, result

    shifts = Shift.objects.filter(
        user_id__in=[cashier_user.id, other_cashier_user.id],
        status=Shift.Status.ACTIVE,
        end_time__isnull=True,
    )
    assert shifts.count() == 2
    assert {shift.device_id for shift in shifts} == {"pytest-terminal"}
