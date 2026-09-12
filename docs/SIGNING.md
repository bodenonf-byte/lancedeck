# Signing LanceDeck with Azure Trusted Signing

Once the exe is signed with Trusted Signing, Windows SmartScreen stops warning about it almost
immediately, and every later build inherits that trust. Cost is about 10 USD a month.

## One-time setup in Azure (about an hour, then a wait of a few days for identity validation)

1. **Azure account.** portal.azure.com, sign up, add a payment method. Create a resource group,
   for instance `lancedeck`.
2. **Trusted Signing account.** Search "Trusted Signing accounts" in the portal, create one:
   name (for instance `lancedeck`), region West Europe or East US, pricing tier Basic.
3. **Identity validation.** In the account, Identity validations → New identity → *Individual*.
   Fill in your legal name and address exactly as on your ID, then complete the verification
   Microsoft emails you (a government ID check through their partner). This is the step that
   takes days.
4. **Certificate profile.** Once validated: Certificate profiles → Create → type *Public Trust*,
   pick the validated identity, name it (for instance `lancedeck-public`). The profile is what
   signs; there is no certificate file to download or keep safe.
5. **Access.** Access control (IAM) on the account → Add role assignment → role
   *Trusted Signing Certificate Profile Signer* → assign it to your own user (for signing from
   this PC) and, for GitHub Actions, to an app registration (Entra ID → App registrations →
   New; create a client secret; note tenant id, client id, secret).
6. **Endpoint.** On the account's overview page, copy the *Account URI*, for instance
   `https://weu.codesigning.azure.net`.

## Signing from this PC

```
Install-Module -Name TrustedSigning -Scope CurrentUser
az login
$env:ATS_ENDPOINT = "https://weu.codesigning.azure.net"
$env:ATS_ACCOUNT  = "lancedeck"
$env:ATS_PROFILE  = "lancedeck-public"
powershell build\build.ps1
```

`build.ps1` calls `build\sign.ps1` at the end; without the three variables it just says it did
not sign. `az login` comes with the Azure CLI (`winget install Microsoft.AzureCLI`).

## Signing on GitHub

`.github/workflows/release.yml` builds the app on a Windows runner whenever you push a tag like
`v0.9.1`, signs it if these repository secrets exist, zips it and attaches it to a draft
release:

| secret | value |
|---|---|
| `AZURE_TENANT_ID` | from the app registration |
| `AZURE_CLIENT_ID` | from the app registration |
| `AZURE_CLIENT_SECRET` | the client secret |
| `ATS_ENDPOINT` | the account URI |
| `ATS_ACCOUNT` | the account name |
| `ATS_PROFILE` | the certificate profile name |

Settings → Secrets and variables → Actions → New repository secret. Without them the workflow
still builds and attaches an unsigned zip.

## Checking a build

```
Get-AuthenticodeSignature dist\LanceDeck\LanceDeck.exe
```

`Status : Valid` and a signer certificate with your name means SmartScreen will see a trusted
publisher. Reputation for a Trusted Signing certificate is usually immediate; if a first
download still warns, it clears within a day or two of downloads.
