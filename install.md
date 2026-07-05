# INSTALL.md — JioPC Automated Testing Agent

Step-by-step installation guide for a fresh Ubuntu 24.04 + LxQt VM [2].

Time budget: ~15 minutes end-to-end (5 minutes for prerequisites,
3-4 minutes for the `.deb` install, and the balance for verification).

---

## 1. Prerequisites

### 1.1 Host machine

You will develop or install into a virtual machine. The host machine
runs your virtualisation software:

- Windows 10/11, macOS, or Linux
- 16 GB RAM recommended (to comfortably run the 8 GB VM plus your host OS)
- 60 GB free disk space (50 GB for the VM disk plus headroom)

### 1.2 Virtualisation software

The submission is validated against a VM, so install one of the free tools [2]:

- **VirtualBox** (Windows, macOS, Linux) — https://www.virtualbox.org/wiki/Downloads
- **VMware Workstation Player** (Windows, macOS) — https://www.vmware.com/products/workstation-player.html

Either works. VirtualBox is used in the examples below.

### 1.3 Ubuntu 24.04 + LxQt VM

The agent is tested and packaged specifically for Ubuntu 24.04 + LxQt [1] [2].

1. Download the Ubuntu 24.04 LTS Desktop ISO:
   https://ubuntu.com/download/desktop

2. In your virtualisation tool, create a new VM with:
   - **Type**: Linux, Version: Ubuntu (64-bit)
   - **CPU**: 4 vCPU (matches JioPC's hardware profile) [2]
   - **RAM**: 8 GB
   - **Disk**: 50 GB minimum, dynamically-allocated
   - **Video**: disable 3D acceleration (JioPC has no GPU) [2]

3. Install Ubuntu 24.04 following the graphical installer prompts.
   Choose a normal installation.

4. Inside the running Ubuntu VM, install LxQt (the desktop environment
   used by JioPC) [1] [2]:

       sudo apt update
       sudo apt install -y lxqt

5. Log out, and at the login screen select the LxQt session, then log
   back in.

6. **Take a VirtualBox snapshot** named `clean-lxqt` before installing
   anything else. This is what the agent expects at runtime — a clean,
   uncustomised environment [1] — and gives you a return point for
   re-testing the `.deb` install.

---

## 2. Install the Agent from the `.deb` Package

The recommended path. The `.deb` handles Python dependencies, Xvfb, and
Playwright's Chromium browser automatically.

### 2.1 Get the `.deb`

Two options:

**Option A — download the pre-built `.deb`.** From the GitHub releases
page or `packaging/out/` directory of the repository:

    cd ~
    # (or scp / drag-and-drop the file into the VM)

The file will be `jiopc-agent_1.0.0_all.deb`.

**Option B — build it from source.** Clone the repository and run the
build script (see Section 4 below for full source-build instructions).

### 2.2 Install with `dpkg` and resolve dependencies

Run these two commands as root:

    sudo dpkg -i ~/jiopc-agent_1.0.0_all.deb
    sudo apt install -f

The first command lays down the source at `/opt/jiopc-agent/` and
installs the `jiopc-agent` wrapper at `/usr/bin/`. It may report unmet
dependencies (Xvfb, python3-pip) and exit non-zero — this is expected.

The second command pulls in the missing system dependencies from
Ubuntu's apt repositories and then triggers the post-install script.
The post-install step:

1. Installs Python runtime dependencies (playwright, psutil, pyxdg,
   pyyaml, openai, httpx) system-wide
2. Downloads Chromium for Playwright, needed by Part A [1]

Expected duration: 3-4 minutes on a typical network.

### 2.3 Verify the install

Run three verification checks:

    # 1. The wrapper is on PATH
    which jiopc-agent
    # Expected output: /usr/bin/jiopc-agent

    # 2. The agent runs Part C (safest, fastest, no launches) [1]
    cd /tmp
    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part C
    # Expected: Part C completes in under 1 second [1]

    # 3. The log was written to the correct user-space path [1]
    ls -la ~/.local/share/jiopc/agent/
    # Expected: test_run_<timestamp>.log file present

If all three succeed, the `.deb` install is complete.

---

## 3. Configure the LLM Analysis Layer

The LLM analysis is a post-run step [1] — configure it separately from
the agent itself. The script is model-agnostic and works with any
OpenAI-compatible endpoint [1].

### 3.1 Choose an LLM provider

Set three environment variables (persist in your shell profile if you
want them permanent):

**Option A — OpenAI:**

    export LLM_BASE_URL=https://api.openai.com/v1
    export LLM_MODEL=gpt-4o
    export LLM_API_KEY=sk-your-key-here

**Option B — local Ollama** (Windows host, VM guest):

    # On Windows host, first run:  ollama pull qwen2.5:7b
    export LLM_BASE_URL=http://10.0.2.2:11434/v1
    export LLM_MODEL=qwen2.5:7b
    export LLM_API_KEY=ollama-local

**Option C — Mistral cloud:**

    export LLM_BASE_URL=https://api.mistral.ai/v1
    export LLM_MODEL=mistral-large-latest
    export LLM_API_KEY=your-mistral-key

Any OpenAI-compatible endpoint works — swap `LLM_BASE_URL` and
`LLM_MODEL` accordingly [1].

### 3.2 Run the agent with analysis

Two-step invocation (matches the spec's example usage) [1]:

    # Step 1 — run the testing agent
    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml

    # Step 2 — analyse the log with an LLM
    python3 /opt/jiopc-agent/analyse.py \
        --log ~/.local/share/jiopc/agent/test_run_<latest>.log

Or the one-step version [1]:

    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --analyse

The LLM analysis prints five sections to your terminal:
executive summary, anomalies grouped by component, patterns &
correlations, risk prioritisation, and a PROMOTE or HOLD
recommendation [1].

### 3.3 Optional — summary email

If you want a formatted summary email sent after the LLM analysis
completes [1], set six additional environment variables:

    export SMTP_HOST=smtp.gmail.com
    export SMTP_PORT=587
    export SMTP_USE_TLS=true
    export SMTP_USER=your-agent@example.com
    export SMTP_PASSWORD=your-app-password
    export EMAIL_FROM=your-agent@example.com
    export EMAIL_TO=devops@example.com,qa-lead@example.com

If any of these variables is missing, the email step is silently
skipped and the LLM analysis still prints to the terminal as normal.

---

## 4. Build the `.deb` From Source (Alternative)

If you prefer to build the package yourself instead of downloading it:

### 4.1 Clone the repository

    git clone https://github.com/itsAmbika/Automated_Testing.git
    cd Automated_Testing

### 4.2 Install build dependencies

    sudo apt update
    sudo apt install -y dpkg-dev

(`dpkg-deb` ships with Ubuntu by default, so this is a small install.)

### 4.3 Run the build script

    ./packaging/build-deb.sh

The built `.deb` appears at:

    packaging/out/jiopc-agent_1.0.0_all.deb

Then follow Section 2 (Install the Agent) using this file.

---

## 5. Test-Data Setup for Part C (Optional)

The agent tests against a JioPC OS Image that ships 15 pre-installed
apps organised into Games, Education, and Productivity desktop
folders [1]. On a plain Ubuntu + LxQt install these folders do not
exist yet, which will cause Part C to report MISPLACED for every
entry [1].

To simulate the JioPC desktop folder structure for realistic Part C
testing, create the folders and populate them with the `.desktop`
files that match your `configs/jiopc-agent.yaml`:

    mkdir -p ~/Desktop/Games ~/Desktop/Education ~/Desktop/Productivity

    # Productivity (7 apps)
    cp /usr/share/applications/featherpad.desktop      ~/Desktop/Productivity/
    cp /usr/share/applications/feathernotes.desktop    ~/Desktop/Productivity/
    cp /usr/share/applications/org.gnome.TextEditor.desktop ~/Desktop/Productivity/
    cp /usr/share/applications/org.gnome.Evince.desktop ~/Desktop/Productivity/
    cp /usr/share/applications/qpdfview.desktop        ~/Desktop/Productivity/
    cp /usr/share/applications/pcmanfm-qt.desktop      ~/Desktop/Productivity/
    cp /usr/share/applications/org.gnome.Calculator.desktop ~/Desktop/Productivity/

    # Education (4 apps)
    cp /usr/share/applications/gucharmap.desktop       ~/Desktop/Education/
    cp /usr/share/applications/yelp.desktop            ~/Desktop/Education/
    cp /usr/share/applications/org.gnome.baobab.desktop ~/Desktop/Education/
    cp /usr/share/applications/org.gnome.eog.desktop   ~/Desktop/Education/

    # Games / Media (4 apps)
    cp /usr/share/applications/audacious.desktop       ~/Desktop/Games/
    cp /usr/share/applications/mpv.desktop             ~/Desktop/Games/
    cp /usr/share/applications/smplayer.desktop        ~/Desktop/Games/
    cp /usr/share/applications/lximage-qt.desktop      ~/Desktop/Games/

With these folders populated, both halves of the Part C check
(desktop-folder placement AND start-menu-category [1]) have real data
to validate against, letting you exercise PASS, MISSING, and MISPLACED
outcomes.

---

## 6. Run the Full Agent

After the `.deb` install and (optionally) Section 5 test-data setup:

    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml

Expected behaviour:
- Runs Part A (web app testing), Part B (native app health), and
  Part C (desktop presence) in sequence [1]
- Total duration under 5 minutes on the standard hardware profile [1]
- Writes a JSON Lines log to `~/.local/share/jiopc/agent/test_run_<timestamp>.log` [1]
- Exits with code 0 if all required tests pass, non-zero otherwise [1]

To run a single component instead of the full sequence [1]:

    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part A
    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part B
    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --part C

Part A alone takes ~30 seconds, Part B alone takes ~3 minutes (with 15
GUI apps launched in Xvfb isolation), and Part C alone takes under 1
second [1].

To run the full agent and immediately analyse the log with an LLM in one
step [1]:

    jiopc-agent --config /opt/jiopc-agent/configs/jiopc-agent.yaml --analyse

---

## 7. Interpret the Log

The log file at `~/.local/share/jiopc/agent/test_run_<timestamp>.log` is
JSON Lines: one JSON object per line, with a final `record_type:"summary"`
record containing the per-component breakdown [1].

Per-test records carry at minimum the fields the spec requires [1]:
`timestamp`, `component` (A/B/C), `test_name`, `result` (PASS / FAIL /
BLOCKED / DEGRADED / MISPLACED / MISSING), `duration_ms`, and a one-line
`detail` message.

Quick log inspection commands:

    LOG=$(ls -t ~/.local/share/jiopc/agent/test_run_*.log | head -1)

    # See just the summary block
    tail -1 "$LOG" | python3 -m json.tool

    # See all non-PASS results
    grep -v '"PASS"' "$LOG" | grep -v record_type | python3 -c '
    import json, sys
    for line in sys.stdin:
        r = json.loads(line)
        print(f"[{r[\"component\"]}] {r[\"test_name\"]:35} {r[\"result\"]:10} {r[\"detail\"]}")
    '

Result semantics per the spec [1]:

- **PASS** — test succeeded
- **FAIL** — genuine regression: timeout, 4xx/5xx, missing binary, or
  process never appeared
- **BLOCKED** — Part A only. Page loaded but showed CAPTCHA / bot-check.
  NOT a regression in the OS Image [1]
- **DEGRADED** — Part B only. Process appeared but terminated before T+5s
  health snapshot [1]
- **MISSING** — Part C only. `.desktop` file not found anywhere on the
  system [1]
- **MISPLACED** — Part C only. `.desktop` file exists but is in the wrong
  desktop folder or wrong start menu category [1]

The exit code follows the same semantics: 0 if all required tests pass,
non-zero if any FAIL / DEGRADED / MISSING / MISPLACED result is present [1].
BLOCKED alone does not flip the exit code because the spec treats it as
distinct from FAIL [1].

---

## 8. Uninstall

To remove the agent while preserving your logs:

    sudo dpkg -r jiopc-agent

To remove the agent AND its configuration files:

    sudo dpkg --purge jiopc-agent

User data in `~/.local/share/jiopc/agent/` is intentionally not touched by
either command — logs from previous runs survive uninstall, matching the
spec's "log files must survive a session restart" constraint [2].

To also remove the Python packages installed by the post-install script:

    sudo pip3 uninstall --break-system-packages -y \
        playwright psutil pyxdg pyyaml openai httpx

To remove Playwright's Chromium browser (~150 MB):

    playwright uninstall chromium

---

## 9. Troubleshooting

**"jiopc-agent: command not found" after install.** The wrapper wasn't
installed to `/usr/bin/`. Verify with `dpkg -L jiopc-agent | grep usr/bin`.
If it's missing, the `.deb` was built without the wrapper — rebuild via
`./packaging/build-deb.sh` and reinstall.

**"[part_b] WARNING: Xvfb binary not found on PATH."** Xvfb is a runtime
dependency for Part B GUI isolation [1]. Install it manually:

    sudo apt install -y xvfb

The agent will still run without Xvfb, but Part B apps will launch on your
real desktop instead of the isolated framebuffer.

**Postinst fails with pip error "externally-managed-environment".** This
happens on Ubuntu 24.04 due to PEP 668. The postinst uses
`--break-system-packages` and `--ignore-installed` to work around this. If
you see the error, run the postinst manually:

    sudo bash -x /var/lib/dpkg/info/jiopc-agent.postinst configure

**Part C reports MISPLACED for every app.** The Games, Education, and
Productivity desktop folders do not exist on a plain Ubuntu install [1].
Follow Section 5 above to create them and populate them with the relevant
`.desktop` files.

**Part B reports DEGRADED for PCManFM-Qt.** This is expected behaviour on
LxQt because PCManFM-Qt is the running desktop manager and handles second
instances via a single-instance handoff. The DEGRADED classification is
spec-correct [1] — the new instance appears briefly and exits before T+5s.
This is documented as a known limitation in `design.md` and does not
indicate an OS Image regression.

**LLM analysis output is incomplete or malformed.** Smaller local models
(< 7B parameters) may drift from the strict five-section output format.
Switch to a 7B+ model (`qwen2.5:7b`, `llama3.1:8b`, `mistral`, or any
hosted OpenAI-compatible endpoint) and lower the temperature:

    export LLM_TEMPERATURE=0.1

**".deb does not install on fresh Ubuntu 24.04 + LxQt system."** This is
an automatic disqualification per Document 1 [2]. If this happens:

1. Restore your VM to a clean snapshot (no partial installs)
2. Verify Ubuntu 24.04 + LxQt (not another Ubuntu variant)
3. Confirm the `.deb` was built with `./packaging/build-deb.sh` and not
   corrupted during transfer
4. Run `sudo dpkg -i` with the full path to the `.deb` file
5. Always follow with `sudo apt install -f` to pull declared dependencies

---

## 10. Verifying a Clean Install for Submission

Before submitting, verify the `.deb` installs cleanly on a fresh
Ubuntu 24.04 + LxQt VM — this is one of the acceptance checklist items [1]
and an automatic disqualification condition if it fails [2]. The correct
verification workflow:

1. Take a snapshot of your VM in the state *before* installing the
   agent (bare Ubuntu 24.04 + LxQt only)
2. Copy the `.deb` to the VM
3. Install with `sudo dpkg -i <path>` and `sudo apt install -f`
4. Verify with the three checks from Section 2.3
5. Restore the VM to the pre-install snapshot
6. Repeat steps 2–4 to confirm reproducibility

If all three checks pass on the clean snapshot on the second attempt, your
`.deb` closes the disqualification gate [2] and passes the corresponding
acceptance-checklist line "`.deb` installs cleanly on fresh Ubuntu 24.04
VM without errors" [1].

---

## References

- **Challenge specification (Document 3 of 4):** JioPC × IIT Bombay Hackathon
  2026, Challenge 02 — Automated Testing Agent [1]
- **Platform overview (Document 1 of 4):** About JioPC & The Challenges [2]
