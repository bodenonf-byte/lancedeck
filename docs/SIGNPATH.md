# Signing LanceDeck through SignPath Foundation

SignPath Foundation signs releases of open-source projects for free. Their certificate is trusted
by Windows, the reputation builds across all projects they sign, and there is no country
restriction. The requirements are all met here: public repository, OSI licence (GPL-3.0), releases
built by a CI pipeline from the public source, and the code signing policy in the README.

## 1. Apply (you)

Go to https://signpath.org/apply and fill in the form:

| field | value |
|---|---|
| Project name | LanceDeck |
| Repository | https://github.com/bodenonf-byte/lancedeck |
| Licence | GPL-3.0 |
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

## Where this stands, and what else there is (2026-09-30)

The application went in on 2026-09-12 and has not been answered. SignPath's own window is two to
four weeks, so it is not late yet. If nothing has arrived by mid-October, write to them quoting the
project name and the repository; their review is done by people and applications do get missed.

Nothing else needs doing until they answer: the workflow step, the secret names and the artifact
configuration above are already in place, so an approval is four secrets and one portal setting
away from a signed release.

### If they say no, or never answer

**Certum Open Source Code Signing** is the realistic fallback. It is issued to individuals, with no
country restriction, against identity documents, and the certificate carries "Open Source
Developer" in its subject. About €29 if you already have their cryptographic card, about €89 for
the card and reader together. The catch is that the certificate lives on that card, so GitHub
Actions cannot sign with it: the CI-built zip would have to be signed on the PC before the release
is published, which breaks the "signed exactly as CI built it" property that SignPath gives for
free. Their cloud version (about €359 a year) can sign from CI.

**Azure Artifact Signing (formerly Trusted Signing) is still closed to us.** Public-trust
certificates for individuals are limited to the United States and Canada. Organisations in
Australia *are* eligible, and since April 2026 a self-employed person may apply as one and the old
three-year-history requirement is gone — so registering as a sole trader is the one route that
could reopen it. Worth a look only if SignPath falls through.

**Do not pay extra for EV.** Since March 2024 an EV certificate no longer grants instant SmartScreen
trust; EV and OV now build reputation the same way, through download volume. There is nothing to
buy that makes the warning disappear on day one.

### What signing will and will not fix

It stops Windows treating the download as from an unknown publisher, and it should end the
"LoadLibrary: Access is denied" failures on `python312.dll` that some people see. It does not give
instant SmartScreen silence: reputation accrues as builds are downloaded, whoever issues the
certificate.
