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

## Three execution modes

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

### 2. Product Sandbox — when product code must be explored

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

### 3. Product-target observer — only when exact production UID/signature matters

This remains a separately signed test artifact. It is not replaced by Product Sandbox and is only needed when the unresolved fact is specifically tied to the installed production application's UID/signature context.

## Custom local probe

If a new hypothesis needs a small one-off Android experiment that is not worth adding to the reusable observer, the agent can use the current research template and run:

```powershell
.\mish-lab.ps1 build
```

Local building is the exception, not the normal path.

## What stays separate

```text
com.mobileproxymish.app
    exact product / RC / E3

com.mobileproxymish.lab.devicefacts
    reusable prebuilt observer

com.mobileproxymish.lab.product
    disposable Product Sandbox
```

## Local layout

```text
C:\mish-lab\
  cache\       exact product APKs and ready probes
  work\        task workspaces owned by the local agent
  results\     submitted typed results
  locks\       single DEVICE-1 lock
```

GitHub Issues are the task/result transport. Raw phone logs and temporary experiments stay local unless a useful capability is deliberately promoted into reusable LAB infrastructure.
