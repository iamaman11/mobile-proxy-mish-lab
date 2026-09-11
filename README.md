# MISH Lab

Local Android research workspace for `iamaman11/mobile-proxy-mish`.

Purpose: make physical Android research boring and repeatable for the local agent.

One loop:

```text
GitHub Issue task -> mish-lab work -> local build/run/research -> result.json -> mish-lab submit -> GitHub Issue result
```

## Operator commands

```powershell
.\mish-lab.ps1 doctor
.\mish-lab.ps1 work <issue-number>
.\mish-lab.ps1 probe build
.\mish-lab.ps1 probe run
.\mish-lab.ps1 status
.\mish-lab.ps1 submit
```

`doctor` checks the host and the currently attached Android device.

`work` downloads one LAB task from a GitHub Issue, verifies its basic contract, creates `C:\mish-lab\work\<task-id>`, and prepares the built-in Android probe when requested.

`probe build` builds the research-only APK from the workspace.

`probe run` installs only the LAB package, runs it, reads a small JSON result through `run-as`, and writes `result.json` in the workspace.

`submit` posts the compact result back to the same Issue.

## Boundaries

MISH Lab is research tooling, not a second product control plane. Product source/releases remain in `iamaman11/mobile-proxy-mish`. Runtime truth remains on Android. LAB raw work stays local.

For now the only hard rules are practical ones:

- do not overwrite the product APK from a LAB task;
- do not store credentials/keystores/device identifiers in this repository;
- serialize work on the single physical phone with one local lock;
- return compact machine-readable results instead of raw logs.

The repository may remain public while it contains only code/contracts. No secret material belongs here.
