from workspace.directory import users_from_response


def test_users_from_response_maps_fields():
    resp = {
        "users": [
            {"primaryEmail": "a@panoramagroup.it",
             "name": {"fullName": "A B"}, "suspended": False, "isAdmin": True},
            {"primaryEmail": "am@panoramagroup.it",
             "name": {"fullName": "AM"}, "suspended": True},
        ]
    }
    users = users_from_response(resp)
    assert users[0] == {
        "email": "a@panoramagroup.it", "full_name": "A B",
        "suspended": False, "is_admin": True,
    }
    assert users[1]["suspended"] is True
    assert users[1]["is_admin"] is False


def test_users_from_response_empty():
    assert users_from_response({}) == []
