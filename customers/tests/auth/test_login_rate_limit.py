import json


def test_one_till_can_try_each_cashier_without_shared_lockout(client):
    for user_id in range(1001, 1009):
        response = client.post(
            "/auth-login",
            data=json.dumps({"user_id": user_id}),
            content_type="application/json",
        )

        assert response.status_code == 422
        assert response.json()["message"] != "Too many requests"
