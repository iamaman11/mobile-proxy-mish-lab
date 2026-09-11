# MISH Lab

Simple local Android research workspace for `iamaman11/mobile-proxy-mish`.

The normal path is intentionally short:

```text
GitHub LAB task -> mish-lab next -> prebuilt probe -> phone -> mish-lab submit -> GitHub result
```

The local agent does **not** build Android code for ordinary observations. CI builds the reusable LAB probe once and publishes it as the `mish-lab-ready-probe` artifact. `mish-lab next` downloads the artifact matching the exact LAB commit, verifies it, and prepares the task.

## Normal operator flow

```powershell
.\mish-lab.ps1 update
.\mish-lab.ps1 doctor
.\mish-lab.ps1 next
.\mish-lab.ps1 run
.\mish-lab.ps1 submit
```

`doctor` requires only Git, GitHub CLI, ADB and exactly one attached Android device. Java/Gradle/Rust are reported as optional capabilities and are needed only for local development experiments.

`next` reads the oldest open `[LAB TASK ...]` Issue, verifies any exact product APK named by the task, creates `C:\mish-lab\work\<task-id>`, and downloads the prebuilt LAB probe when the task uses the standard observer.

`run` installs/updates only `com.mobileproxymish.lab.devicefacts`, runs it on the attached phone and writes the compact typed `result.json`.

`submit` posts that result to the task Issue, closes the Issue and releases the phone lock.

## When the ready probe is not enough

For a one-off custom research probe the agent can use:

```powershell
.\mish-lab.ps1 build
```

This copies the research template into the current workspace and builds it locally. This is the exception, not the default.

For experiments that need the real product source path, use a Product Sandbox task and:

```powershell
.\mish-lab.ps1 sandbox prepare
.\mish-lab.ps1 sandbox build
.\mish-lab.ps1 sandbox run
```

Product Sandbox checks out the exact requested `mobile-proxy-mish` SHA into the task workspace and changes only the disposable Android `applicationId` to:

```text
com.mobileproxymish.lab.product
```

so it can be installed beside the real product APK. The source copy is disposable and may be freely edited by the local agent for research.

## What stays separate

```text
com.mobileproxymish.app
    exact product / RC / E3

com.mobileproxymish.lab.devicefacts
    reusable prebuilt observer

com.mobileproxymish.lab.product
    disposable Product Sandbox
```

If a question fundamentally requires the exact production UID/signature relationship, a separately signed product-target observer is still required. Do not use Product Sandbox as proof of a production-UID-specific fact.

## Local layout

```text
C:\mish-lab\
  cache\       downloaded product APKs and ready probes
  work\        task workspaces owned by the local agent
  results\     submitted typed results
  locks\       single DEVICE-1 lock
```

The GitHub repository contains infrastructure and task contracts. Raw phone logs and temporary experiments remain local unless a task explicitly turns a useful capability into reusable LAB code.
