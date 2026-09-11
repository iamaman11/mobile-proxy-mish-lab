# MISH Lab

Simple local Android research workspace for `iamaman11/mobile-proxy-mish`.

The default local operator interface is one command:

```powershell
.\mish-lab.ps1 go
```

For PRODUCT physical acceptance, build activation is deliberately separate from the phone: choose one exact accepted PRODUCT `main` SHA and post that SHA as the entire comment in permanent control Issue **#11**. GitHub-hosted LAB CI builds the candidate; the local agent only consumes and tests it.

For general LAB tasks, `go` keeps the existing task flow as a fallback.

## PRODUCT physical E3 — standard path

Permanent natural owner:

`#11 [LAB CONTROL] PRODUCT physical candidate — build / test activation`

The complete standard procedure is:

```text
decide exact green iamaman11/mobile-proxy-mish/main SHA
-> comment exactly that lowercase 40-char SHA in LAB Issue #11
-> GitHub-hosted builder validates source/main/CI identity
-> build app-debug.apk + app-debug-androidTest.apk once
-> verify package/signature/native payload
-> publish candidate.json + both APKs as one Actions artifact
-> post READY or FAILED to Issue #11
-> local agent runs .\mish-lab.ps1 go
-> LAB downloads and independently verifies the exact artifact
-> install/run PRODUCT physical E3 on DEVICE-1
-> post typed RESULT back to Issue #11
```

No new LAB task Issue is created for each PRODUCT build. The activation comment itself is immutable evidence: its GitHub comment ID is the request identity.

A valid activation comment must:

- be on Issue #11;
- be authored by `iamaman11`;
- contain only one lowercase 40-character SHA;
- point to a commit in `iamaman11/mobile-proxy-mish` `main` history;
- have a successful exact-SHA `push` run of PRODUCT `.github/workflows/ci.yml`.

Everything else fails closed or is ignored by the activation job.

The artifact name is derived from request comment ID + exact source SHA. `candidate.json` binds:

- permanent control Issue number;
- immutable request comment ID;
- exact PRODUCT source SHA;
- LAB workflow SHA and build run;
- PRODUCT/test package names;
- instrumentation runner/test class;
- target ABI;
- SHA-256 of PRODUCT APK and androidTest APK;
- signing-certificate SHA-256.

The candidate is explicitly `PHYSICAL_TEST_CANDIDATE_NOT_RELEASE`. `mobile-proxy-mish` remains the sole PRODUCT source of truth; LAB owns only the derived build/test evidence.

The local machine does **not** need Gradle, Rust, cargo-ndk or Android build tooling for this path. `product_physical_control.py` resolves the latest uncompleted request in #11, waits fail-closed for its READY artifact, then reuses `product_physical_e3.py` for exact candidate verification and physical execution.

The physical executor:

```text
download exact request/source artifact
-> independently verify candidate.json + both APK SHA-256 values
-> require exactly one SM-A022G / API 30 / armeabi-v7a device
-> install PRODUCT + matching androidTest APK
-> launch PRODUCT
-> allow a bounded Magisk grant window
-> run CellularE3InstrumentedTest through AndroidJUnitRunner
-> keep raw instrumentation output local only
-> post typed RESULT keyed by request comment ID + source SHA
```

No automatic uninstall is allowed on signing conflicts. `INSTALL_FAILED_UPDATE_INCOMPATIBLE` stops with an explicit action-required error rather than deleting an installed PRODUCT package. A first Magisk grant for `com.mobileproxymish.app` remains an explicit device security action; LAB does not bypass it.

Hosted build failures are terminally recorded as `PRODUCT_PHYSICAL_CANDIDATE=FAILED`, so local `go` never waits forever for a failed build. A posted `PRODUCT_PHYSICAL_RESULT` makes that activation terminal; the same request is not accidentally rerun.

Durable GitHub results contain typed E3 evidence and immutable artifact identities, not carrier public IPs, DNS addresses, ADB serials or raw instrumentation logs.

## General ready-probe tasks

For a normal ready-probe task `go` performs:

```text
update LAB
-> doctor
-> get next GitHub LAB task
-> verify/cache exact product APK when requested
-> download the prebuilt probe matching the exact LAB commit
-> install/run it on the attached phone
-> collect typed result
-> post result to the task Issue
-> close the task
```

No Android build is required for ordinary observations.

CI builds the reusable LAB probe once and publishes it as the `mish-lab-ready-probe` artifact. The local tool downloads only the artifact produced for its exact checked-out LAB commit and verifies the APK digest from `probe.json`.

## Useful manual commands

The one-command path is preferred, but general LAB steps remain individually available:

```powershell
.\mish-lab.ps1 update
.\mish-lab.ps1 doctor
.\mish-lab.ps1 next
.\mish-lab.ps1 run
.\mish-lab.ps1 status
.\mish-lab.ps1 submit
```

`doctor` requires Git, GitHub CLI, ADB and exactly one attached Android device. Java/Gradle/Rust are optional and are needed only when the agent deliberately develops a local experiment.

## Execution modes

### Ready probe

```text
GitHub task
-> prebuilt com.mobileproxymish.lab.devicefacts
-> physical phone
-> typed result
```

The observer returns normal device/network facts plus a non-mutating cellular socket-bind matrix on the same validated direct cellular `Network` when one is available. It does not toggle radios, change network configuration, connect test sockets, or modify PRODUCT. Network handles, IP addresses and raw logcat stay transient.

### PRODUCT physical E3

Uses permanent control Issue #11 as described above. New PRODUCT E3 work must not create a second activation owner. Older per-task PRODUCT E3 support remains only for already-issued legacy tasks during migration.

### Product Sandbox

A Product Sandbox task checks out the exact requested `mobile-proxy-mish` source SHA into a disposable task workspace and changes only its Android application ID to:

```text
com.mobileproxymish.lab.product
```

It can then be installed beside the real product. Commands:

```powershell
.\mish-lab.ps1 sandbox prepare
.\mish-lab.ps1 sandbox build
.\mish-lab.ps1 sandbox run
```

Local building is an explicit research exception, not the normal PRODUCT acceptance path.

### Product-target observer

This remains a separately signed test artifact and is only needed when the unresolved fact is specifically tied to the installed production application's signature context.

## Ownership

```text
mobile-proxy-mish/main
    sole PRODUCT source of truth

LAB Issue #11 comments
    exact PRODUCT physical build/test activation log

com.mobileproxymish.app + com.mobileproxymish.app.test
    exact-source candidate pair derived by hosted LAB CI

com.mobileproxymish.lab.devicefacts
    reusable prebuilt observer

com.mobileproxymish.lab.product
    disposable Product Sandbox
```

## Local layout

```text
C:\mish-lab\
  cache\       exact physical candidates and ready probes
  work\        general task workspaces
  results\     typed results and local-only raw physical instrumentation
  locks\       DEVICE-1 lock for legacy/general task execution
```

Raw phone logs and temporary experiments stay local unless a useful capability is deliberately promoted into reusable LAB infrastructure.
