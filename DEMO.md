# The 2-minute demo: screen-recording script

**The story in one line:** all green, then a bug sneaks in, and the report and GitHub show exactly what broke and why.

You'll show, in order: (1) a clean run, all green; (2) the same run with a bug switched on, which names what broke; (3) the HTML report; (4) the red cross and the pull-request comment on GitHub.

Everything here runs without Ollama, API keys or WhatsApp. Part 4 needs a pull request prepared in advance, because GitHub takes a few minutes to run its checks.

---

## Before you record (about 15 minutes, once)

### A. Set up the terminal

1. Open **PowerShell**. Make the text big: hold **Ctrl** and scroll the mouse wheel up a few notches.
2. Go to the project and switch on the Python environment:

```powershell
cd C:\dev\wa-agent-test
```

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run that, run `Set-ExecutionPolicy -Scope Process Bypass` first, then try again.

3. Check everything is healthy (this is also a warm-up; you want to see `0 newly broken, 0 fixed, 30 unchanged`):

```powershell
python scripts/ci_run.py
```

### B. Prepare the GitHub pull request (so the red cross is ready)

This puts the one-word bug (a button renamed from "Dates" to "Date") on a throwaway branch and opens a pull request. **Never do this on `main`.**

```powershell
git switch -c demo-bug
```

```powershell
python scripts/demo_break.py on
```

```powershell
git commit -am "Demo: rename a button (breaks scenarios on purpose)"
```

```powershell
git push -u origin demo-bug
```

Then in your browser open **https://github.com/aiteam31-star/wa-agent-test/pull/new/demo-bug** and click **Create pull request**.

Wait about 3 to 10 minutes. When it's ready the pull request shows **red crosses** (two checks fail, the project's own tests and **Scenarios**) and a **comment from github-actions** with a table of what broke (4 scenarios). Refresh the page if you don't see it.

Now go back to the good code locally:

```powershell
git switch main
```

```powershell
python scripts/demo_break.py status
```

That last command must say `the bug is OFF`. If it says ON, run `python scripts/demo_break.py off`.

### C. Arrange your screen

- Browser tab 1: the **pull request page** (red crosses and the comment visible; scroll so both show).
- Browser tab 2: the repository's **Actions** page (shows the green run on `main`).
- Close everything else. Turn off notifications (Windows: Focus assist / Do not disturb). Browser zoom about 125%.
- Start the recorder: press **Win + Shift + R** (Snipping Tool), drag a box around the whole screen, click **Start**. (OBS Studio works too.) Click **Stop** when you're done.

---

## The script (about 2 minutes)

| Time | On screen | Say | Do |
|---|---|---|---|
| 0:00 to 0:12 | Terminal, empty | "Testing a WhatsApp AI agent usually means someone typing into a phone and eyeballing the answers. This plays WhatsApp and the customer for you." | nothing yet |
| 0:12 to 0:35 | Terminal: the clean run | "Here's a demo bot that answers questions about five fictional IPOs. Thirty conversations, all green, in a few seconds. This is our known-good baseline." | run **command 1** and point at `30 passed` and `0 newly broken, 0 fixed, 30 unchanged` |
| 0:35 to 1:00 | Terminal: the bug | "Now I switch on a bug: the bot gives a wrong listing date. Same run." Point at the red lines: "Six scenarios newly broken, each with the reason: reply says 1 December, data says 30 November." | run **command 2**, then **command 3**: "exit code 1, which is what makes a build fail" |
| 1:00 to 1:25 | Browser: the HTML report | "And the report. Newly broken first. Here's the actual chat: the customer asks when Nova Textiles lists, the bot says 1 December, and the check explains why that's wrong." | run **command 4**; scroll to **listing-date-fact: Nova Textiles** (it starts open), point at the chat and the red box |
| 1:25 to 2:00 | Browser: GitHub | "On GitHub it runs on every pull request. Here's a change that renames a button: red cross, and the summary is posted right on the pull request, with the report to download." | tab 1: point at the red cross, then the **github-actions** comment table; click **Details** on Scenarios, scroll to **Artifacts**, point at **scenario-report**. Tab 2: "and `main` stays green." |

If you finish early: stop. Don't pad.

### The commands, in order

Run these in the PowerShell window you prepared. Pause a second after each so the output is readable.

**Command 1.** The clean run (about 8 seconds):

```powershell
python scripts/ci_run.py
```

**Command 2.** The same run with the wrong-date bug switched on (`| Select-Object -Last 22` keeps just the part worth seeing on screen):

```powershell
python scripts/ci_run.py --force listing_date | Select-Object -Last 22
```

**Command 3.** Show that it failed:

```powershell
$LASTEXITCODE
```

It prints `1`. (`0` means success; anything else makes a CI build fail.)

**Command 4.** Open the report in your browser:

```powershell
Invoke-Item reports\ci\report.html
```

Then switch to the pull-request tab for the GitHub part (nothing to type).

### Optional bonus (30 more seconds): all three bugs at once

This shows the message WhatsApp would reject and the combined "rejected ... also ..." lines. Run it, then open the report again and press **Ctrl+F** to find **no-investment-advice**.

```powershell
python scripts/ci_run.py --force buttons,advice,listing_date | Select-Object -Last 10
```

```powershell
Invoke-Item reports\ci\report.html
```

In the report you'll see a dashed red bubble marked **NOT DELIVERED** (the bot tried to send four buttons; WhatsApp allows three), and a red box such as `rejected: has 4 buttons; at most 3 allowed` followed by `also: reply must not contain ['you should apply']`.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `python` or `ci_run.py` not found | You're not in the project folder or the environment isn't on: redo step A.2. |
| The pull request shows no comment | Wait a little longer, refresh. The comment appears after the **Scenarios** check finishes. Check that the pull request is from `demo-bug`, not a fork. |
| The pull request is green | The bug wasn't on when you committed. Run `python scripts/demo_break.py status` on the branch (`git switch demo-bug` first); it must say ON. |
| Command 2 says `0 newly broken` | The bug flag didn't take. Check you typed `--force listing_date` (two dashes). |
| Port errors | Close other copies of the demo and rerun; ports are picked at random each time. |

---

## After you record

1. **Clean up the pull request** (deleting its branch closes it):

```powershell
git switch main
```

```powershell
git push origin --delete demo-bug
```

```powershell
git branch -D demo-bug
```

2. **Take the screenshot for the README** (it currently shows a placeholder): run command 2, run command 4, scroll the report to the top so the headline `6 newly broken, 0 fixed, 24 unchanged` and the first red scenario are visible, press **Win + Shift + S**, drag around the page, and save the image as `C:\dev\wa-agent-test\docs\images\report.png`. Then ask for the README line to be switched from the placeholder to `report.png`, and commit and push.
3. Make sure the real code is still clean:

```powershell
python scripts/demo_break.py status
```

It must say `the bug is OFF`.
