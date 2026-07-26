"""Unit tests for compute_release.py's pure logic: commit parsing, bump
determination, and version arithmetic. No git/filesystem I/O — those are
exercised by running the script for real in the release job, not here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from compute_release import (  # noqa: E402
    Commit, determine_bump, bump_version, group_commits, render_notes, render_rollback,
)


def c(subject, body=''):
    return Commit(sha='abcdef1234567890', subject=subject, body=body)


def test_commit_parses_type_scope_description():
    commit = c('feat(scheduling): add SLA reminders')
    assert commit.type == 'feat'
    assert commit.scope == 'scheduling'
    assert commit.description == 'add SLA reminders'


def test_commit_without_conventional_prefix_is_other():
    commit = c('updated some stuff')
    assert commit.type == 'other'
    assert commit.description == 'updated some stuff'


def test_breaking_change_via_bang():
    commit = c('feat!: drop legacy endpoint')
    assert commit.is_breaking is True


def test_breaking_change_via_footer():
    commit = c('fix: adjust response shape', body='BREAKING CHANGE: field renamed')
    assert commit.is_breaking is True


def test_non_breaking_commit():
    commit = c('fix: correct off-by-one error')
    assert commit.is_breaking is False


def test_determine_bump_major_wins_over_everything():
    commits = [c('fix: small thing'), c('feat!: big change'), c('feat: another thing')]
    assert determine_bump(commits) == 'major'


def test_determine_bump_minor_when_feat_present_no_breaking():
    commits = [c('fix: small thing'), c('feat: new capability')]
    assert determine_bump(commits) == 'minor'


def test_determine_bump_patch_for_fix_only():
    assert determine_bump([c('fix: correct bug')]) == 'patch'


def test_determine_bump_patch_default_for_unconventional_commits():
    # Safe default: a push to main with no recognizable conventional commits
    # still produces a release rather than silently doing nothing.
    assert determine_bump([c('misc updates'), c('wip')]) == 'patch'


def test_determine_bump_none_when_no_commits():
    assert determine_bump([]) == 'none'


def test_bump_version_major_minor_patch():
    assert bump_version('v1.2.3', 'major') == 'v2.0.0'
    assert bump_version('v1.2.3', 'minor') == 'v1.3.0'
    assert bump_version('v1.2.3', 'patch') == 'v1.2.4'


def test_bump_version_accepts_tag_without_v_prefix():
    assert bump_version('1.2.3', 'patch') == 'v1.2.4'


def test_group_commits_buckets_by_label():
    commits = [c('feat: a'), c('fix: b'), c('chore: c'), c('docs: d')]
    groups = group_commits(commits)
    assert {commit.description for commit in groups['Features']} == {'a'}
    assert {commit.description for commit in groups['Bug Fixes']} == {'b'}
    assert {commit.description for commit in groups['Other Changes']} == {'c', 'd'}


def test_render_notes_includes_scope_and_short_sha():
    notes = render_notes('v1.1.0', 'v1.0.0', [c('feat(api): add endpoint')])
    assert '**api**: add endpoint' in notes
    assert 'abcdef1' in notes
    assert '# v1.1.0' in notes


def test_render_notes_omits_empty_groups():
    notes = render_notes('v1.0.1', 'v1.0.0', [c('fix: bug')])
    assert '## Bug Fixes' in notes
    assert '## Features' not in notes


def test_render_rollback_normal_case_has_revert_command():
    doc = render_rollback('v1.1.0', 'v1.0.0', 'acr.azurecr.io', 'app', 'rg', 'app-name', False)
    assert 'az containerapp update' in doc
    assert '--image acr.azurecr.io/app:1.0.0' in doc
    assert 'v1.1.0 -> v1.0.0' in doc


def test_render_rollback_first_release_has_no_nonsensical_self_revert():
    doc = render_rollback('v1.0.0', None, 'acr.azurecr.io', 'app', 'rg', 'app-name', False)
    assert 'az containerapp update' not in doc
    assert 'first release' in doc.lower()
    assert 'v1.0.0 -> v1.0.0' not in doc
