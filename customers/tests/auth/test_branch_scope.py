"""Cashier login branch-scope tests."""

import pytest
from django.test import override_settings

from base.models import User
from base.security.hashing import hash_password
from customers.services.auth_service import AuthService


pytestmark = pytest.mark.django_db


def _cashier(*, branch_id, email):
    return User.objects.create(
        first_name="Branch",
        last_name="Cashier",
        email=email,
        password=hash_password("1234"),
        role=User.RoleChoices.CASHIER,
        status=User.UserStatus.ACTIVE,
        branch_id=branch_id,
    )


@pytest.mark.parametrize("identity_branch", ["", "cloud", "CLOUD"])
@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_global_cashier_identity_can_log_in_on_bound_local_branch(
    identity_branch,
):
    cashier = _cashier(
        branch_id=identity_branch,
        email=f'global-{identity_branch or "blank"}@test.local',
    )

    result, status = AuthService.login(
        email=cashier.email,
        password="1234",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert status == 200, result
    assert result["data"]["user"]["branch_id"] == "branch1"


@override_settings(
    DEPLOYMENT_MODE="local",
    BRANCH_ID="branch1",
    ENFORCE_BRANCH_LOGIN=True,
)
def test_concrete_foreign_cashier_identity_is_denied_on_local_branch():
    cashier = _cashier(
        branch_id="branch2",
        email="foreign-cashier@test.local",
    )

    result, status = AuthService.login(
        email=cashier.email,
        password="1234",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert status == 403
    assert result["message"] == "You are not authorized for this branch"
