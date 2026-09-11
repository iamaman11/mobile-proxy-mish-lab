# MISH Lab

Simple local Android research workspace for `iamaman11/mobile-proxy-mish`.

The default operator interface is one command:

```powershell
.\mish-lab.ps1 go
```

For a normal ready-probe task it performs the whole loop:

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

The one-command path is preferred, but every step remains individually available:

```powershell
.\mish-lab.ps1 update
.\mish-lab.ps1 doctor
.\mish-lab.ps1 next
.\mish-lab.ps1 run
.\mish-lab.ps1 status
.\mish-lab.ps1 submit
```

`doctor` requires Git, GitHub CLI, ADB and exactly one attached Android device. Java/Gradle/Rust are optional and are needed only when the agent deliberately develops a local experiment.

## Four execution modes

### 1. Ready probe — default

```text
GitHub task
-> prebuilt com.mobileproxymish.lab.devicefacts
-> physical phone
-> typed result
```

The prebuilt observer currently returns the normal device/network facts plus a non-mutating cellular socket-bind matrix on the same validated direct cellular `Network` when one is available:

```text
Framework Network.bindSocket(FileDescriptor)
NDK android_setsocknetwork() + immediate errno
x IPv4 / IPv6
x fresh direct FD / dup-detach-adopt FD
```

It does not toggle radios, change network configuration, connect the test sockets, or modify the product. Network handles, IP addresses and raw logcat stay transient; the durable result contains only typed observations, PASS/FAIL, errno and a classification.

The local agent normally just runs `mish-lab.ps1 go`.

### 2. PRODUCT physical E3 — hosted build, local execution

This is the normal path when an exact accepted `mobile-proxy-mish/main` commit must be tested on DEVICE-1 without creating a Release first.

A task has the bounded shape:

```json
{
  "schema": "mish.lab-task/v1",
  "task_id": "LAB-0001",
  "operation": "research.manual",
  "execution": "product_physical_e3",
  "product": {
    "repo": "iamaman11/mobile-proxy-mish",
    "source_sha": "<exact 40-char accepted-main SHA>"
  }
}
```

Opening or reopening that LAB task triggers `.github/workflows/product-physical-candidate.yml`. The hosted builder fails closed unless the requested SHA is in the PRODUCT `main` history and has a successful exact-SHA push run of `.github/workflows/ci.yml`.

The builder then uses the PRODUCT pinned Android/Rust toolchain and creates one immutable Actions artifact:

```text
mish-product-e3-LAB-NNNN-<source_sha>/
  candidate.json
  app-debug.apk
  app-debug-androidTest.apk
```

`candidate.json` binds the artifact to the exact PRODUCT source SHA, LAB workflow SHA, build run, package names, runner/test class, ABI, signing-certificate digest and SHA-256 of both APKs. The artifact is explicitly `PHYSICAL_TEST_CANDIDATE_NOT_RELEASE`; PRODUCT source remains owned only by `mobile-proxy-mish`.

The local machine does not build Android. After the hosted candidate is ready, the local agent runs only:

```powershell
.\mish-lab.ps1 go
```

The existing LAB task owner selects the task and takes the DEVICE-1 lock. `product_physical_e3.py` then:

```text
download exact task/source artifact
-> independently verify candidate.json + both APK SHA-256 values
-> require exactly one SM-A022G / API 30 / armeabi-v7a device
-> install PRODUCT + matching androidTest APK
-> launch PRODUCT
-> allow a bounded Magisk grant window
-> run CellularE3InstrumentedTest through AndroidJUnitRunner
-> persist raw instrumentation output locally only
-> write a typed mish.lab-result/v1
-> submit/close the LAB task through the existing mish_lab.py owner
```

No automatic uninstall is allowed on signing conflicts. `INSTALL_FAILED_UPDATE_INCOMPATIBLE` stops with an explicit action-required error rather than deleting an installed PRODUCT package. A first Magisk grant for `com.mobileproxymish.app` remains an explicit device security action; LAB does not bypass it.

Durable GitHub results contain typed E3 evidence and immutable artifact identities, not carrier public IPs, DNS addresses, ADB serials or raw instrumentation logs.

### 3. Product Sandbox — when product code must be explored

A Product Sandbox task checks out the exact requested `mobile-proxy-mish` source SHA into the disposable task workspace and changes only its Android application ID to:

```text
com.mobileproxymish.lab.product
```

It can then be installed beside the real product. The local agent may edit this disposable copy freely for research.

Commands:

```powershell
.\mish-lab.ps1 sandbox prepare
.\mish-lab.ps1 sandbox build
.\mish-lab.ps1 sandbox run
```

`go` automatically prepares the workspace and stops there for a Product Sandbox task instead of pretending the research can be automated.

### 4. Product-target observer — only when exact production UID/signature matters

This remains a separately signed test artifact. It is not replaced by Product Sandbox or the debug physical E3 candidate and is only needed when the unresolved fact is specifically tied to the installed production application's signature context.

## Custom local probe

If a new hypothesis needs a small one-off Android experiment that is not worth adding to the reusable observer, the agent can use the current research template and run:

```powershell
.\mish-lab.ps1 build
```

Local building is the exception, not the normal path.

## What stays separate

```text
mobile-proxy-mish/main
    only PRODUCT source of truth

com.mobileproxymish.app + com.mobileproxymish.app.test
    exact-source physical E3 candidate pair derived by LAB hosted CI

com.mobileproxymish.lab.devicefacts
    reusable prebuilt observer

com.mobileproxymish.lab.product
    disposable Product Sandbox
```

## Local layout

```text
C:\mish-lab\
  cache\       exact product APKs, physical candidates and ready probes
  work\        task workspaces owned by the local agent
  results\     submitted typed results
  locks\       single DEVICE-1 lock
```

GitHub Issues are the task/result transport. Raw phone logs and temporary experiments stay local unless a useful capability is deliberately promoted into reusable LAB infrastructure.
