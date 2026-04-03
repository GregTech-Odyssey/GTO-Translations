# Contributing

## Config

Project configuration is stored in `.paratranz-sync.yml`.

- `release.product`: release prefix, currently `gto`
- `release.primary_project_id`: Paratranz project used as the version source
- `projects`: supported locales and their Paratranz project IDs

## Sync

`Sync Paratranz Translations` does the following:

1. Runs tests.
2. Pulls translations from Paratranz.
3. Resolves the release line from the primary project's `extra.version`.
4. Builds resource-pack artifacts.
5. Uploads artifacts.
6. Commits generated translation changes back to the repository when needed.

If non-primary projects report a different `extra.version`, the workflow emits a GitHub Actions warning and continues.

## Release

Stable releases are published by pushing a Git tag.

`Publish Stable Release` is triggered by tags matching:

`gto-*-r*`

example: `gto-0.5.4-r1`

It rebuilds artifacts from the tagged commit and publishes a GitHub Release automatically.


Release steps:

1. Choose the synced commit you want to publish.
2. Create an annotated tag.
3. Push the tag to GitHub.
4. GitHub Actions will build and publish the release automatically.

Example:

```bash
git checkout <commit>
git tag -a gto-0.5.4-r1 -m "Stable translation release gto-0.5.4-r1"
git push origin gto-0.5.4-r1
```

## Adding a New Locale

If you want to add support for a new language, please contact [GregTech-Odyssey](https://github.com/GregTech-Odyssey) first. Opening an issue in the main repository or reaching out through the GTO Discord are both fine.

GregTech-Odyssey will create and own the corresponding Paratranz project before the language is added to this repository:

1. Ownership of the Paratranz project does not mean the translation is official content. The project is still community-maintained.
2. GregTech-Odyssey keeps Paratranz project ownership so that if the original contributor or organizer of a locale steps away, the project can still be operated and the translation workflow can remain stable.
3. By contributing translation content through the Paratranz project, contributors agree that their contributions may be distributed under this repository's CC BY-NC-SA 4.0 license.

After the Paratranz project is created, contributors should join that project on Paratranz and do the translation work there.

Once the Paratranz project is ready, submit a pull request that updates the repository configuration and automation:

1. Add the new locale and Paratranz project ID to `.paratranz-sync.yml`.
2. Update `.github/workflows/paratranz-sync.yml` so the new locale artifact is uploaded by the sync workflow.
3. Update `.github/workflows/stable-release.yml` so the new locale package is included in stable releases.
4. Update `README.md` if the downloadable package list needs to mention the new locale.

Please do not submit translation files directly by pull request. The source of truth should remain the Paratranz project for that language.
