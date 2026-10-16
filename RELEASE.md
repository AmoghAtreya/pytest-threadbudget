# Release procedure

The release workflow reruns the complete CI workflow, builds distributions, then
publishes those artifacts through PyPI trusted publishing. It requires a tag
`vVERSION` matching `pyproject.toml`. No PyPI API token is stored in this project.

For the first release, the PyPI account owner must add a pending GitHub publisher
at https://pypi.org/manage/account/publishing/ with these exact fields:

- PyPI project name: `pytest-threadbudget`
- GitHub owner: `AmoghAtreya`
- Repository: `pytest-threadbudget`
- Workflow filename: `publish.yml`
- Environment: `pypi`

This grants that workflow authority to publish this package. Restrict repository
write access and review changes to release workflows carefully. The environment
must match the workflow and PyPI configuration exactly.

1. Update the version in pyproject.toml and src/pytest_threadbudget/__init__.py,
   and write the changelog. Remove stale local dist/ files before rebuilding.
2. Run the checks in CONTRIBUTING.md and inspect the public CI results.
3. Commit and push the final source. Tag that commit `vVERSION` and push the tag.
4. Create a GitHub release from that tag. Publishing triggers automatically.
   To retry a failed release after fixing account configuration, manually run
   `publish.yml` with the same tag selected.
5. Verify the PyPI project, install the published version into a fresh environment,
   run the smoke example, and confirm wheel metadata and pytest registration.

Never overwrite a published version. Fixes require a new version. Adoption and
upstream acceptance are tracked separately from successful publication.
