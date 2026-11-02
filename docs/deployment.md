# Deploying to Streamlit Community Cloud

Streamlit Community Cloud hosts Streamlit apps from a GitHub repository for free. AuditLens needs no
secrets, database or data files: when `data/` is absent it generates the synthetic demo ledger in
memory on first load and caches it (about 10 seconds on a fast laptop; allow up to a minute or two on a cold
free-tier machine).

## Steps

1. **Check the repository is ready.** `app.py` is at the repo root, `requirements.txt` has pinned
   dependencies, and `config.yaml` and `.streamlit/config.toml` are committed. `data/` and `outputs/` are
   git-ignored on purpose.
2. **Make the repo reachable.** A public repository is the simplest. A private one also works if you
   authorise Streamlit to read it, but then only people you invite can open the app unless you change its
   sharing settings. If you want recruiters to open the link, make the repository public first
   (GitHub: Settings, then Danger Zone, then Change visibility).
3. Go to <https://share.streamlit.io>, sign in with GitHub and choose **Create app**.
4. Pick the repository `Vivan-coder/auditlens`, branch `main`, main file path `app.py`.
5. Open **Advanced settings** and choose **Python 3.13** (the version the project is developed and tested on).
   No secrets are required.
6. Click **Deploy**. The first build installs the pinned requirements (a few minutes). Add the resulting
   URL to the top of the README.

Deep links work: `https://<your-app>.streamlit.app/?page=Review%20queue` (pages: Overview, Review queue,
Entry detail, Benford analysis, Evaluation, Data upload).

## Behaviour to know about

* **First load is slower.** Generating and analysing 50,000 lines takes about 10 seconds locally, but a test from a
  brand-new environment took about a minute. A spinner ("Preparing the demo ledger") is shown. The result is
  cached for every later visitor until the app restarts.
* **Memory.** The app holds one dataset in memory (a few hundred MB at most). Community Cloud's free tier
  is enough; if it ever restarts, it simply regenerates.
* **No persistence.** Reviewer statuses and notes live in each visitor's session; export to Excel to keep
  them. Uploaded files are processed in memory and are not saved, but this is a public portfolio demo, so
  **do not upload confidential data**.
* **Apps sleep** after a period of inactivity; the first visitor wakes it (and triggers regeneration).
* **No `pip install -e .` needed.** `app.py` adds `src/` to the import path.

## Troubleshooting

| Symptom | Likely cause and fix |
|---------|----------------------|
| Build fails on a package version | Re-pin in `requirements.txt` to a version available for the selected Python, then re-run `pytest` locally |
| `ModuleNotFoundError: auditlens` | The app must be launched from the repo root so `app.py` can find `src/`; check the main file path is `app.py` |
| App is slow on first visit | Expected: the demo ledger is generated once, then cached |
| Evaluation page says labels are missing | You are viewing uploaded data, which has no ground truth. Switch the sidebar dataset back to Demo data |
