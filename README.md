# MISH Lab

Local Windows/Android diagnostic workspace for `iamaman11/mobile-proxy-mish`.

## Ownership

`iamaman11/mobile-proxy-mish` is the sole PRODUCT source/build/release authority.

Formal PRODUCT acceptance does **not** build Android in this repository and does **not** use a LAB prerelease as PRODUCT identity.

The accepted path is:

```text
mobile-proxy-mish protected main
 -> PRODUCT CI PASS
 -> read-only Cloudflare live preflight PASS
 -> Android Release Candidate workflow
 -> one immutable PRODUCT RC
 -> E3 Physical Cellular workflow on Windows LAB + phone
 -> E4 real-client acceptance on the same RC
 -> PROXY_ON_PHONE_WORKING=YES
```

The PRODUCT repository owns:

- source and reviewed workflows;
- immutable RC tag/release identity;
- signed PRODUCT APK;
- release manifest and PRODUCT APK SHA-256;
- exact E3 instrumentation harness artifact from the same RC build;
- formal E3/E4 evidence orchestration.

This LAB repository owns only reusable local diagnostics/research helpers and general device probes.

## No second PRODUCT build path

The historical Issue #11 / `product-physical-candidate.yml` flow that rebuilt `app-debug.apk` in this repository is retired.

Do not:

- copy PRODUCT APK files into this repository;
- rebuild PRODUCT here for E3/E4;
- create LAB prereleases as formal PRODUCT candidates;
- use `latest` or an unverified APK as acceptance identity;
- put Android release signing secrets on the LAB host.

Formal E3 is launched from the protected PRODUCT repository workflow:

```text
.github/workflows/e3-physical-cellular.yml
```

That workflow resolves the current immutable RC, verifies exact release tag/source/APK digest/signing certificate, resolves the matching same-source E3 harness artifact, and only then executes the physical Windows/Android stage. The physical host is a consumer of those bytes, never a builder.

## Default local diagnostic command

```powershell
.\mish-lab.ps1 go
```

`go` now handles only the general LAB task queue. It no longer polls Issue #11 or activates a PRODUCT build/acceptance flow.

Typical general flow:

```text
update LAB
 -> doctor
 -> get next LAB task
 -> download/verify the task's exact probe or diagnostic input
 -> run against the attached phone
 -> collect typed result
 -> submit result
```

Useful commands:

```powershell
.\mish-lab.ps1 update
.\mish-lab.ps1 doctor
.\mish-lab.ps1 next
.\mish-lab.ps1 run
.\mish-lab.ps1 status
.\mish-lab.ps1 submit
```

`doctor` requires Git, GitHub CLI, ADB and exactly one attached Android device for phone work. Java/Gradle/Rust are optional research tooling, not PRODUCT acceptance prerequisites.

## Ready probe

The reusable LAB probe is `com.mobileproxymish.lab.devicefacts`.

```text
GitHub LAB CI
 -> prebuilt ready probe
 -> local agent downloads exact artifact for the checked-out LAB commit
 -> physical phone
 -> typed diagnostic result
```

The probe may observe bounded device/network facts. Raw network handles, public addresses and raw logs stay local unless a specific evidence contract requires a redacted projection.

## Legacy helpers

Historical `product_physical_e3.py` / related diagnostic code may remain temporarily for already-issued legacy diagnostic tasks. They are not formal E3 authority and may not promote `PROXY_ON_PHONE_WORKING`.

New formal PRODUCT physical work must use the PRODUCT repository's immutable-RC workflows.

## Product Sandbox

A sandbox may deliberately build a disposable application under:

```text
com.mobileproxymish.lab.product
```

for local research only:

```powershell
.\mish-lab.ps1 sandbox prepare
.\mish-lab.ps1 sandbox build
.\mish-lab.ps1 sandbox run
```

Sandbox bytes are never PRODUCT release or acceptance bytes.

## Local layout

```text
C:\mish-lab\
  cache\       downloaded probes/diagnostic inputs
  work\        disposable task workspaces
  results\     typed results and local-only raw diagnostics
  locks\       serialized physical-device execution
```

The guiding rule is:

```text
one PRODUCT build authority
one immutable RC identity
one physical acceptance path
LAB only consumes/observes
```
