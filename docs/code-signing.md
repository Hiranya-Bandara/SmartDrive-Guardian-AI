# Code signing (optional, not done for 2.0.0)

SmartDrive Guardian AI 2.0.0 is **not code-signed**. No certificate was purchased, and none is
simulated. Users therefore see a Windows SmartScreen warning ("Windows protected your PC" /
"Unknown publisher") and should verify the published SHA-256 checksums instead
([installation.md](installation.md)). Do not ask users to turn off SmartScreen or antivirus
protection.

## What signing would add

An Authenticode signature binds the executable and installer to a verified publisher identity
and lets Windows detect any modification. SmartScreen reputation builds up per certificate.
Checksums alone only show that a file matches what was published.

## Steps for a future release

1. Obtain a code-signing certificate (OV or EV) or use a signing service such as Azure Trusted
   Signing. Keep the key in a hardware token or the service; never commit it, and never store it
   as a plain file in CI.
2. Sign the PyInstaller executable after `scripts\build-windows.ps1` and before the ZIP and
   installer are created:

   ```powershell
   signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a `
     ".\dist\SmartDrive-Guardian-AI\SmartDrive-Guardian-AI.exe"
   ```

3. Let Inno Setup sign the installer and uninstaller: define a sign tool in the Inno Setup IDE
   or with `ISCC.exe "/Ssigntool=signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 /a $f"`,
   then add `SignTool=signtool` and `SignedUninstaller=yes` to `[Setup]` in
   `packaging\installer.iss`.
4. Run `scripts\generate-checksums.ps1` **after** signing (signing changes the files) and
   `scripts\verify-release.ps1`, which reports each signature's status.
5. In GitHub Actions, use the signing provider's official action with secrets scoped to the
   `release` environment only.
