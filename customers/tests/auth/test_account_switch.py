import json


def _login(client, user):
    return client.post(
        "/auth-login",
        data=json.dumps(
            {
                "user_id": user.pk,
                "password": "cashierpass",
            }
        ),
        content_type="application/json",
    )


def test_cashier_switch_replaces_stale_cookie_and_authenticates_new_user(
    client,
    cashier_user,
    other_cashier_user,
):
    first_login = _login(client, cashier_user)

    assert first_login.status_code == 200
    first_token = first_login.json()["data"]["token"]
    assert client.cookies["session_key"].value == first_token

    second_login = _login(client, other_cashier_user)

    assert second_login.status_code == 200
    second_token = second_login.json()["data"]["token"]
    assert second_token != first_token
    assert second_login.cookies["session_key"].value == second_token
    assert client.cookies["session_key"].value == second_token

    me = client.get("/auth-me")

    assert me.status_code == 200
    assert me.json()["data"]["id"] == other_cashier_user.pk
