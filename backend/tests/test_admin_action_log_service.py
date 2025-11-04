from app.services.admin_action_log import list_actions, log_admin_action
from tests._auth_helpers import create_db_user


def test_log_admin_action_creates_a_record():
    actor_id = create_db_user("admin")
    before = len(list_actions())
    log_admin_action(
        actor_id=actor_id,
        actor_role="admin",
        actor_org_id=1,
        action="role_change",
        target_type="user",
        target_id=999,
        detail={"from_role": "patient", "to_role": "provider"},
    )
    after = list_actions()
    assert len(after) == before + 1
    assert after[0].action == "role_change"
    assert after[0].detail == {"from_role": "patient", "to_role": "provider"}
    assert after[0].target_id == "999"


def test_log_admin_action_never_raises_on_bad_target_id_type():
    actor_id = create_db_user("admin")
    # None target_id is a valid, real case (e.g. org creation before an
    # id exists yet in some hypothetical caller) — must not raise.
    log_admin_action(
        actor_id=actor_id,
        actor_role="admin",
        actor_org_id=1,
        action="test_action",
        target_type="nothing",
        target_id=None,
    )


def test_list_actions_scoped_to_org_for_org_admin():
    actor_a = create_db_user("org_admin")
    actor_b = create_db_user("org_admin")

    before_a = len(list_actions(org_id=101))
    log_admin_action(
        actor_id=actor_a, actor_role="org_admin", actor_org_id=101,
        action="role_change", target_type="user", target_id=1,
    )
    log_admin_action(
        actor_id=actor_b, actor_role="org_admin", actor_org_id=102,
        action="role_change", target_type="user", target_id=2,
    )

    org_101_actions = list_actions(org_id=101)
    org_102_actions = list_actions(org_id=102)
    assert len(org_101_actions) == before_a + 1
    assert all(a.actor_org_id == 101 for a in org_101_actions)
    assert all(a.actor_org_id == 102 for a in org_102_actions)


def test_list_actions_unrestricted_when_org_id_is_none():
    actor_id = create_db_user("admin")
    log_admin_action(
        actor_id=actor_id, actor_role="admin", actor_org_id=999,
        action="role_change", target_type="user", target_id=1,
    )
    all_actions = list_actions(org_id=None)
    assert any(a.actor_org_id == 999 for a in all_actions)


def test_list_actions_respects_limit():
    actor_id = create_db_user("admin")
    for i in range(5):
        log_admin_action(
            actor_id=actor_id, actor_role="admin", actor_org_id=1,
            action="role_change", target_type="user", target_id=i,
        )
    assert len(list_actions(limit=2)) == 2


def test_list_actions_most_recent_first():
    actor_id = create_db_user("admin")
    log_admin_action(
        actor_id=actor_id, actor_role="admin", actor_org_id=1,
        action="first_action", target_type="user", target_id=1,
    )
    log_admin_action(
        actor_id=actor_id, actor_role="admin", actor_org_id=1,
        action="second_action", target_type="user", target_id=2,
    )
    actions = list_actions(limit=2)
    assert actions[0].action == "second_action"
    assert actions[1].action == "first_action"
