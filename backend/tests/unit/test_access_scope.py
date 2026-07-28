"""Unit tests for the access-scope helpers in server.py — these are the security
boundary the whole app relies on (every list/detail endpoint and the LLM chat
snapshot all filter through these), so bugs here mean real data leaks across
projects/roles. High-risk path, deserves direct, thorough coverage.
"""
import server


def test_non_pm_roles_get_account_wide_scope(make_user):
    for role in ('service_line_leader', 'staffing', 'tech_architect', 'admin'):
        user = make_user(role=role)
        assert server.scope_project_ids(user) is None
        assert server.scope_filter(user) == {}


def test_pm_scope_limited_to_assigned_projects(make_project, make_user):
    proj_a = make_project(name='Phoenix')
    proj_b = make_project(name='Atlas')
    pm = make_user(role='pm', project_ids=[proj_a['id']])
    ids = server.scope_project_ids(pm)
    assert ids == [proj_a['id']]
    assert server.scope_filter(pm) == {'project_id': {'$in': [proj_a['id']]}}
    # proj_b was never assigned to this PM.
    assert proj_b['id'] not in ids


def test_pm_with_no_assignments_sees_nothing(make_user):
    pm = make_user(role='pm')
    assert server.scope_project_ids(pm) == []


def test_pos_in_scope_true_for_account_wide_roles(make_project, make_user, make_position):
    project = make_project()
    position = make_position(project['id'])
    sll = make_user(role='service_line_leader')
    assert server.pos_in_scope(sll, position) is True


def test_pos_in_scope_false_for_pm_outside_project(make_project, make_user, make_position):
    own_project = make_project(name='Phoenix')
    other_project = make_project(name='Atlas')
    position = make_position(other_project['id'])
    pm = make_user(role='pm', project_ids=[own_project['id']])
    assert server.pos_in_scope(pm, position) is False


def test_pos_in_scope_true_for_pm_inside_project(make_project, make_user, make_position):
    project = make_project()
    position = make_position(project['id'])
    pm = make_user(role='pm', project_ids=[project['id']])
    assert server.pos_in_scope(pm, position) is True
