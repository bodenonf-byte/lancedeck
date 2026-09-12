# Signing LanceDeck through SignPath Foundation

SignPath Foundation signs releases of open-source projects for free. Their certificate is trusted
by Windows, the reputation builds across all projects they sign, and there is no country
restriction. The requirements are all met here: public repository, OSI licence (MIT), releases
built by a CI pipeline from the public source, and the code signing policy in the README.

## 1. Apply (you)

Go to https://signpath.org/apply and fill in the form:

| field | value |
|---|---|
| Project name | LanceDeck |
| Repository | https://github.com/bodenonf-byte/lancedeck |
| Licence | MIT |
| Description | Free, unofficial team tracker for MechWarrior Online. Reads the player's own screen locally (OCR) and shows both teams as lances, live; records every match. No memory reading, no input, nothing online. |
| Build system | GitHub Actions (`.github/workflows/release.yml`) |
| Artifacts | `LanceDeck-<version>-win64.zip` containing `LanceDeck.exe` (PyInstaller) |
| Your role | Author and maintainer |

They review the project, usually within two to four weeks, and email you when the certificate is
approved with the two values below.

## 2. Configure the repository (you, once approved)

SignPath gives you an **organization id** and a **project slug**, and you create an **API token**
in their portal. Put them in the repository: Settings → Secrets and variables → Actions.

| secret | value |
|---|---|
| `SIGNPATH_API_TOKEN` | the API token from the SignPath portal |
| `SIGNPATH_ORG_ID` | the organization id |
| `SIGNPATH_PROJECT` | the project slug, for instance `lancedeck` |
| `SIGNPATH_POLICY` | `release-signing` |

In the SignPath project, the artifact configuration must say what to sign inside the zip:

```xml
<artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
  <zip-file>
    <directory path="LanceDeck">
      <pe-file path="LanceDeck.exe">
        <authenticode-sign/>
      </pe-file>
    </directory>
  </zip-file>
</artifact-configuration>
```

## 3. Release

Push a tag, `v0.9.1` for instance. The workflow builds the app on a GitHub runner, sends the zip
to SignPath, waits for the signed zip, and attaches it to a draft release. Publish the draft.
SignPath only signs artifacts built by the CI pipeline, never a zip uploaded from a PC, which is
the point: anyone can check that the signed binary came from the public source.
