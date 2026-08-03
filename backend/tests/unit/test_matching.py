"""Unit tests for match_interviewer's scoring logic: skill overlap dominates,
load only breaks ties, excluded (declined) interviewers are never offered again.
"""
from db import db
import server


def test_prefers_higher_skill_overlap_over_lower_load(make_position, make_project, make_interviewer):
    project = make_project()
    position = make_position(project['id'], skills=['python', 'kubernetes', 'aws'])
    make_interviewer('LowMatchLowLoad', skills=['python'])
    high_match = make_interviewer('HighMatchSomeLoad', skills=['python', 'kubernetes', 'aws'])
    # Even with existing load, 3/3 skill overlap (score 30-1=29) beats 1/3 overlap
    # with zero load (score 10-0=10).
    db.interviews.insert_one({'id': 'iv-1', 'interviewer_id': high_match['id'], 'result': None,
                              'invite_status': 'pending'})

    best, reason, slot = server.match_interviewer(position, exclude_ids=[])
    assert best['id'] == high_match['id']
    assert '3/3' in reason
    assert slot is None


def test_excludes_declined_interviewers(make_position, make_project, make_interviewer):
    project = make_project()
    position = make_position(project['id'], skills=['react'])
    declined = make_interviewer('Declined', skills=['react'])
    fallback = make_interviewer('Fallback', skills=['react'])

    best, _, _ = server.match_interviewer(position, exclude_ids=[declined['id']])
    assert best['id'] == fallback['id']


def test_ignores_inactive_interviewers(make_position, make_project, make_interviewer):
    project = make_project()
    position = make_position(project['id'], skills=['go'])
    make_interviewer('Inactive', skills=['go'], active=False)

    best, _, _ = server.match_interviewer(position, exclude_ids=[])
    assert best is None


def test_returns_none_when_no_interviewers_available(make_position, make_project):
    project = make_project()
    position = make_position(project['id'], skills=['rust'])
    best, reason, slot = server.match_interviewer(position, exclude_ids=[])
    assert best is None
    assert reason == ''
    assert slot is None


def test_prefers_interviewer_with_availability_when_skills_and_load_tie(make_position, make_project, make_interviewer):
    project = make_project()
    position = make_position(project['id'], skills=['react'])
    make_interviewer('NoAvailability', skills=['react'])
    has_slot = make_interviewer('HasAvailability', skills=['react'], availability=['2099-01-01T10:00:00'])

    best, reason, slot = server.match_interviewer(position, exclude_ids=[])
    assert best['id'] == has_slot['id']
    assert slot == '2099-01-01T10:00:00'
    assert 'next available slot' in reason


def test_ignores_past_availability_slots(make_position, make_project, make_interviewer):
    project = make_project()
    position = make_position(project['id'], skills=['react'])
    make_interviewer('OnlyPastSlot', skills=['react'], availability=['2000-01-01T10:00:00'])

    best, reason, slot = server.match_interviewer(position, exclude_ids=[])
    assert best is not None
    assert slot is None
    assert 'no declared availability' in reason


def test_returns_earliest_future_slot(make_position, make_project, make_interviewer):
    project = make_project()
    position = make_position(project['id'], skills=['react'])
    make_interviewer('MultiSlot', skills=['react'],
                     availability=['2099-03-01T10:00:00', '2099-01-15T09:00:00', '2099-02-01T08:00:00'])

    _, _, slot = server.match_interviewer(position, exclude_ids=[])
    assert slot == '2099-01-15T09:00:00'
