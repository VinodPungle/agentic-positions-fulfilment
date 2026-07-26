"""Compute the next SemVer release from Conventional Commits since the last tag,
generate categorized release notes, and generate a rollback plan document.

Deliberately not using a third-party tool (semantic-release, release-please, etc.):
the bump/grouping logic is simple enough that a small, transparent, unit-tested
script is easier to review and trust than a plugin-configured Node dependency,
and it avoids adding an npm toolchain to a backend CI job that has no other use
for one.

Version bump rules (standard Conventional Commits mapping):
    - "BREAKING CHANGE:" in the body, or "!" after the type/scope (e.g. "feat!:")
      -> major
    - type "feat" -> minor
    - type "fix" or "perf" -> patch
    - anything else (docs/chore/refactor/test/ci/build/unparseable) -> patch
      (a safe default so every push to main still produces a versioned release,
      rather than silently producing nothing when commit messages don't follow
      the convention)
The overall bump for a release is the highest-severity bump among its commits.

Usage (from repo root):
    python scripts/compute_release.py --output-dir releases

Writes releases/vX.Y.Z-NOTES.md and releases/vX.Y.Z-ROLLBACK.md, and prints
GITHUB_OUTPUT-format lines to stdout (or to $GITHUB_OUTPUT if set) for the
calling workflow to consume: version, previous_version, has_changes.
"""
import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass

CONVENTIONAL_RE = re.compile(r'^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$')

TYPE_LABELS = {
    'feat': 'Features',
    'fix': 'Bug Fixes',
    'perf': 'Performance',
}
OTHER_LABEL = 'Other Changes'


@dataclass
class Commit:
    sha: str
    subject: str
    body: str = ''

    @property
    def _match(self):
        return CONVENTIONAL_RE.match(self.subject)

    @property
    def is_breaking(self) -> bool:
        if re.search(r'BREAKING[ -]CHANGE:', self.body):
            return True
        m = self._match
        return bool(m and m.group('breaking'))

    @property
    def type(self) -> str:
        m = self._match
        return m.group('type').lower() if m else 'other'

    @property
    def scope(self) -> str:
        m = self._match
        return m.group('scope') if m and m.group('scope') else ''

    @property
    def description(self) -> str:
        m = self._match
        return m.group('desc') if m else self.subject


def determine_bump(commits: list) -> str:
    """Highest-severity bump across all commits. 'patch' if there are commits but
    none are feat/breaking, so a push to main always produces a release."""
    if not commits:
        return 'none'
    if any(c.is_breaking for c in commits):
        return 'major'
    if any(c.type == 'feat' for c in commits):
        return 'minor'
    return 'patch'


def bump_version(previous: str, bump: str) -> str:
    """previous like 'v1.2.3' (leading 'v' optional) -> next 'vX.Y.Z'."""
    major, minor, patch = (int(p) for p in previous.lstrip('v').split('.'))
    if bump == 'major':
        return f'v{major + 1}.0.0'
    if bump == 'minor':
        return f'v{major}.{minor + 1}.0'
    if bump == 'patch':
        return f'v{major}.{minor}.{patch + 1}'
    raise ValueError(f'unknown bump level: {bump}')


def group_commits(commits: list) -> dict:
    groups = {}
    for c in commits:
        label = TYPE_LABELS.get(c.type, OTHER_LABEL)
        groups.setdefault(label, []).append(c)
    return groups


def render_notes(version: str, previous_version: str, commits: list) -> str:
    groups = group_commits(commits)
    lines = [f'# {version}', '']
    if previous_version:
        lines.append(f'Changes since `{previous_version}`:')
        lines.append('')
    ordered_labels = ['Features', 'Bug Fixes', 'Performance', OTHER_LABEL]
    for label in ordered_labels:
        if label not in groups:
            continue
        lines.append(f'## {label}')
        for c in groups[label]:
            scope_prefix = f'**{c.scope}**: ' if c.scope else ''
            lines.append(f'- {scope_prefix}{c.description} ({c.sha[:7]})')
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def render_rollback(version: str, previous_version, acr_login_server: str,
                    image_repo: str, resource_group: str, container_app: str,
                    touched_db_layer: bool) -> str:
    if not previous_version:
        # First release ever tracked by this pipeline — there's no prior versioned
        # image to fall back to. Say so plainly rather than rendering a nonsensical
        # "roll back to itself" doc.
        revert_section = (
            "This is the first release tracked by this pipeline — there is no prior\n"
            "versioned image to revert to here. To roll back, redeploy whatever image tag\n"
            "was running before this pipeline existed (check `az containerapp revision list`\n"
            f"for `{container_app}`'s revision history), or restore from Azure's\n"
            "deployment/activity log for the resource group."
        )
    else:
        revert_section = f'''```
az containerapp update \\
  -g {resource_group} -n {container_app} \\
  --image {acr_login_server}/{image_repo}:{previous_version.lstrip('v')}
```
This points the Container App back at the exact image that was running before
`{version}` was deployed — no rebuild needed, the image is already in the registry.'''

    db_note = (
        "This release changed database-layer code (db.py / index definitions or similar).\n"
        "MongoDB does not support automatic 'down' migrations — before or after rolling\n"
        "back the app, manually review the diff for this release for any index changes\n"
        f"(`git diff {previous_version or version}..{version} -- backend/db.py`) and confirm\n"
        "whether any index needs to be manually dropped/recreated to match the reverted code."
        if touched_db_layer else
        "No database-layer code changed in this release — reverting the container image\n"
        "is sufficient, no index/schema reversal needed."
    )
    return f'''# Rollback plan: {version} -> {previous_version or "(none — first release)"}

## When to use this
The `{version}` deployment is misbehaving (elevated error rate, failed health checks,
broken functionality) and needs to be reverted to the last known-good release.

## 1. Revert the deployment
{revert_section}

## 2. Database / config
{db_note}

## 3. Verify the rollback succeeded
- `az containerapp revision list -g {resource_group} -n {container_app} --query "[].{{name:name,health:properties.healthState,traffic:properties.trafficWeight}}" -o table`
  — confirm the new revision is `Healthy` and has 100% traffic.
- `curl https://<app-fqdn>/api/` — confirm a 200 response.
- Check Application Insights (`requests` and `exceptions` tables) for the 5-10 minutes
  after rollback — error rate should return to baseline, no new exception spike.
- If the original issue was reported by a user, confirm with them that it's resolved.

## 4. Follow-up
File an issue capturing what went wrong in `{version}` before re-attempting the release.
'''


def _run_git(args, cwd):
    result = subprocess.run(['git'] + args, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def get_previous_tag(repo_root: str):
    try:
        return _run_git(['describe', '--tags', '--abbrev=0', '--match=v*'], repo_root)
    except subprocess.CalledProcessError:
        return None


def get_commits_since(repo_root: str, previous_tag) -> list:
    range_spec = f'{previous_tag}..HEAD' if previous_tag else 'HEAD'
    # Use a delimiter unlikely to appear in commit messages to split subject/body/sha.
    fmt = '%H%x1f%s%x1f%b%x1e'
    raw = _run_git(['log', range_spec, f'--pretty=format:{fmt}'], repo_root)
    commits = []
    for record in filter(None, raw.split('\x1e')):
        parts = record.strip('\n').split('\x1f')
        if len(parts) != 3:
            continue
        sha, subject, body = parts
        commits.append(Commit(sha=sha, subject=subject, body=body))
    return commits


def touched_db_layer(repo_root: str, previous_tag) -> bool:
    if not previous_tag:
        return True  # can't compare — assume yes, safer default for a rollback doc
    range_spec = f'{previous_tag}..HEAD'
    changed = _run_git(['diff', '--name-only', range_spec, '--', 'backend/db.py', 'backend/seed.py'], repo_root)
    return bool(changed.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', default='.')
    parser.add_argument('--output-dir', default='releases')
    parser.add_argument('--acr-login-server', default=os.environ.get('ACR_LOGIN_SERVER', ''))
    parser.add_argument('--image-repo', default='agentic-fulfilment-app')
    parser.add_argument('--resource-group', default=os.environ.get('AZURE_RESOURCE_GROUP', ''))
    parser.add_argument('--container-app', default=os.environ.get('CONTAINER_APP_NAME', ''))
    args = parser.parse_args()

    previous_tag = get_previous_tag(args.repo_root)
    commits = get_commits_since(args.repo_root, previous_tag)
    bump = determine_bump(commits)

    outputs = {}
    if bump == 'none':
        outputs['has_changes'] = 'false'
        outputs['version'] = previous_tag or ''
        outputs['previous_version'] = previous_tag or ''
    else:
        version = bump_version(previous_tag, bump) if previous_tag else 'v1.0.0'
        os.makedirs(os.path.join(args.repo_root, args.output_dir), exist_ok=True)

        notes = render_notes(version, previous_tag, commits)
        notes_path = os.path.join(args.output_dir, f'{version}-NOTES.md')
        with open(os.path.join(args.repo_root, notes_path), 'w', encoding='utf-8') as f:
            f.write(notes)

        rollback = render_rollback(
            version, previous_tag, args.acr_login_server, args.image_repo,
            args.resource_group, args.container_app,
            touched_db_layer(args.repo_root, previous_tag))
        rollback_path = os.path.join(args.output_dir, f'{version}-ROLLBACK.md')
        with open(os.path.join(args.repo_root, rollback_path), 'w', encoding='utf-8') as f:
            f.write(rollback)

        outputs = {
            'has_changes': 'true',
            'version': version,
            'previous_version': previous_tag or '',
            'bump': bump,
            'notes_path': notes_path,
            'rollback_path': rollback_path,
        }

    output_target = os.environ.get('GITHUB_OUTPUT')
    lines = [f'{k}={v}' for k, v in outputs.items()]
    if output_target:
        with open(output_target, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines), file=sys.stderr)


if __name__ == '__main__':
    main()
