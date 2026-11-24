# Put this project on GitHub and watch the checks run

This guide is for someone who has never used GitHub. Every step says what to click or type, and why.

## The big picture (read this first)

- **Git** is the history-keeping tool already on your computer. Every time we "committed", Git saved a snapshot of the project. Right now those snapshots exist **only on your PC**.
- **GitHub** is a website that stores a copy of that history, so it's backed up and shareable.
- **GitHub Actions** is a robot on GitHub. Whenever you send (push) new snapshots, it starts a clean computer, installs the project, and runs the checks we wrote (`.github/workflows/`). You see a green tick if everything is fine and a red cross if not.

Two workflows run automatically:

| Name on GitHub | What it does |
|---|---|
| **CI** | Checks the code (style, types) and runs the project's own tests. |
| **Scenarios** | Starts the demo bot, runs all 30 chat scenarios, compares them with the saved "known good" results (`baselines/demo-bot.json`), uploads the HTML report, and on pull requests posts a summary comment. **It turns red if any scenario is newly broken.** |

Neither needs a password, an API key or an AI model: CI uses the fake brain and the fake judge.

## Step 0: save your latest work on your PC

Open PowerShell in the project folder and run these one at a time. They save the newest changes as a snapshot (a "commit").

```powershell
cd C:\dev\wa-agent-test
```

```powershell
git status --short
```

If that lists files, save them:

```powershell
git add -A
```

```powershell
git commit -m "Add GitHub Actions workflow and CI baseline"
```

## Step 1: create your GitHub account

1. Go to <https://github.com/signup>.
2. Enter your email, a password, and a **username**. The username is public and is part of your project's web address, so pick something you're happy to show people.
3. Solve the puzzle, then check your email for the verification code and enter it.
4. Skip any optional questions.
5. Strongly recommended: turn on two-factor sign-in (click your picture, then **Settings**, then **Password and authentication**).

## Step 2: tell Git your name (so your work is labelled as yours)

Right now Git has no name saved for you, and all 13 existing snapshots say they were made by a placeholder, "wa-agent-test dev <dev@example.invalid>". That is harmless, but you probably want your own name on future work.

1. On GitHub, open **Settings**, then **Emails**. Tick **Keep my email addresses private**. GitHub then shows you a private address that looks like `12345678+yourname@users.noreply.github.com`. Copy it. Using it means your real email never appears in the project's history.
2. Back in PowerShell (use your own name and that private address):

```powershell
git config --global user.name "Your Name"
```

```powershell
git config --global user.email "12345678+yourname@users.noreply.github.com"
```

**Optional, only before your first push:** to also relabel the 13 old snapshots as yours, run this once. It rewrites the history (safe now, because nothing has been published yet):

```powershell
git rebase -r --root --exec "git commit --amend --reset-author --no-edit"
```

If you skip it, the old snapshots keep the placeholder author. That does no harm.

## Step 3: create an empty project ("repository") on GitHub

1. On github.com, click the **+** at the top right, then **New repository**.
2. **Repository name:** `wa-agent-test`.
3. **Public or Private?** Private means only you (and people you invite) can see it; public means anyone can. If you're unsure, choose **Private**; you can change it later. (Public repositories get free Actions minutes with no limit; private ones have a generous free monthly allowance, which is plenty for this project.)
4. **Leave all the "initialise" boxes unticked**: no README, no .gitignore, no licence. Your project already has them, and adding them here would make the first push fail.
5. Click **Create repository**. You'll land on a page showing a web address like `https://github.com/yourname/wa-agent-test.git`. Keep that page open.

## Step 4: send your project to GitHub ("push")

In PowerShell, in the project folder. Your branch is called `master`; GitHub's default is `main` (and the CI workflow is set up for `main`), so rename it first:

```powershell
git branch -M main
```

Tell Git where the GitHub copy lives. Replace `yourname` with your GitHub username:

```powershell
git remote add origin https://github.com/yourname/wa-agent-test.git
```

Send everything:

```powershell
git push -u origin main
```

The first time, a window opens asking you to sign in to GitHub in your browser (this uses Git Credential Manager, which came with Git for Windows). Approve it. **Don't type your GitHub password into the terminal; GitHub no longer accepts passwords there.** When the push finishes, refresh your repository page: your files are there.

What those commands mean: `origin` is just the nickname for "the GitHub copy", and `-u origin main` says "send my `main` branch there, and remember that pairing".

## Step 5: watch the workflow run

1. On your repository page, click the **Actions** tab. Pushing started two runs: **CI** and **Scenarios**.
2. Each run shows a yellow dot while it works (a few minutes), then a **green tick** (all good) or a **red cross** (something failed).
3. Click **Scenarios**, then the latest run. You'll see:
   - the job and its steps (click a step to read what it printed);
   - the **summary** text, for example `0 newly broken, 0 fixed, 30 unchanged`;
   - at the very bottom, an **Artifacts** section with **scenario-report**. Click it to download a zip, unzip it, and open `report.html` in your browser. That's the chat-style report.
4. If a run is red, click into it, click the red step and read the last lines of its log. Copy them to me and I'll help. (I could only test on Windows, so the very first run on GitHub's Linux machines might show a small difference I couldn't see.)

## Step 6: see it catch a problem (a safe experiment)

This shows the red cross, the report, and the comment on a "pull request" (a proposal to merge a change). You'll break something on purpose, on a separate branch, so `main` stays safe.

1. Make a branch for the experiment:

```powershell
git switch -c try-a-bug
```

2. Open `demo_bot/agent.py` in any editor. Near the top find the line that starts with `BUTTON_TITLES` and change `"Dates"` to `"Date"` (one letter). Save the file.
3. Save and send the change:

```powershell
git commit -am "Experiment: rename a button"
```

```powershell
git push -u origin try-a-bug
```

4. On your repository page a yellow banner appears: **Compare & pull request**. Click it, then **Create pull request**.
5. Wait a few minutes. On the pull request page you'll see:
   - a red cross next to **Scenarios** (it failed because scenarios are newly broken; in my test, 4 of them);
   - a **comment from github-actions** with a table of what broke and why;
   - under **Checks**, a link to the run and its downloadable report.
6. Fix it: change `"Date"` back to `"Dates"`, then:

```powershell
git commit -am "Undo the experiment"
```

```powershell
git push
```

The run starts again, turns green, and the same comment updates itself (it doesn't pile up new ones).
7. Tidy up: close the pull request (**Close pull request** at the bottom) and, if you like, delete the branch.

Optional later: to make GitHub refuse to merge a pull request whose **Scenarios** check is red, go to **Settings**, **Branches**, **Add branch protection rule**, pick `main`, tick **Require status checks to pass before merging**, and choose **scenarios**.

## When you change the bot or the scenarios on purpose

CI compares against `baselines/demo-bot.json`, the saved "known good" result. If you add a scenario or deliberately change what the bot says, make sure everything you expect is passing, then refresh the baseline and save it:

```powershell
python scripts/ci_run.py --save-baseline
```

```powershell
git add baselines/demo-bot.json
```

```powershell
git commit -m "Update the CI baseline"
```

Don't refresh the baseline just to make a red run green: that would hide a real problem.

## What CI does not do

- It uses the **fake brain** and the **fake judge**, so it proves the harness and the simple checks (dates, prices, button counts, advice phrases) still work. It does not test a real AI model; the fake judge says "pass" to everything. Run the project on your own computer with Ollama for that.
- It needs no secrets. Never put an API key into a file in the repository; if you ever add a real AI judge to CI, store the key in **Settings**, **Secrets and variables**, **Actions**.
- Pull requests from someone else's copy ("fork") can't post comments (GitHub protects the repository); the check and the downloadable report still work.

## Words you'll see

| Word | Meaning |
|---|---|
| repository (repo) | the project folder on GitHub, with all its history |
| commit | one saved snapshot of the project |
| push | send your commits to GitHub |
| branch | a separate line of work (`main` is the main one) |
| pull request (PR) | a proposal to merge one branch into another, with a place to discuss and see checks |
| workflow | a recipe the GitHub robot follows (a file in `.github/workflows/`) |
| artifact | a file a workflow saves for you to download (our HTML report) |
