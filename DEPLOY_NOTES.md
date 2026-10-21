# Deploy notes: web/ to Azure Static Web Apps (Free)

The site is `web/` exactly as committed. No build step runs on the host:
`web/data/` is built locally with `python src/build_site.py` and committed.
Deploys run from `.github/workflows/azure-static-web-apps.yml` on every push
to `main` that changes `web/` or the workflow, or by hand from the Actions tab.

Never paste the deployment token into a file, a commit, an issue or a chat.
It goes only into the GitHub secret below.

## Before you start

- `python src/build_site.py` and `python -m pytest` pass, and `git status` is clean.
- The workflow and `web/staticwebapp.config.json` are committed but not yet
  pushed, or pushed knowing the first run fails until the secret exists.

## 1. Azure portal

1. Go to portal.azure.com and check the subscription and directory at the top right.
2. Search **Static Web Apps** and select **+ Create**.
3. **Basics** tab:
   - Subscription: yours
   - Resource group: **Create new**, e.g. `rg-xt-match-web` (separate from Foundry)
   - Name: e.g. `xt-match-assistant`
   - Plan type: **Free**
   - Region (if asked): any; nothing runs there
   - Source: **Other** (not GitHub; GitHub would commit its own workflow to `main`)
4. **Review + create**: check that the plan shows Free. Then **Create**.
5. Wait for "Your deployment is complete" and select **Go to resource**.
6. **Overview**: note the **URL**. It shows Azure's "waiting for content" page for now.
7. **Manage deployment token**: copy the token.

## 2. GitHub

1. Repo **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `AZURE_STATIC_WEB_APPS_API_TOKEN`. Value: the token. Select **Add secret**.
3. Push `main`, or go to **Actions → Deploy web/ to Azure Static Web Apps → Run workflow**.
4. The run should turn green in a minute or two. The log skips the app build
   and ends with "Status: Succeeded. Visit your site at: …".

## 3. Final URL

`https://<two-random-words>-<random-hex>.<digit>.azurestaticapps.net`.
The exact address is on the resource's Overview page.

Query parameters work on it, e.g. `…azurestaticapps.net/?t=245`.

## 4. Check the live page

- Private window and phone; play at 60x; switch all four profiles; **Show the move** on an older card.
- `?t=245` opens at 04:05 in the 1st half; `?t=5760` opens at full time, 2–1.
- DevTools **Network**: every request goes to the site's own host.
- DevTools **Console**: no errors and no Content-Security-Policy violations.

## 5. Roll back

- **Bad content:** `git revert <commit>`, then `git push`. The workflow redeploys the previous `web/`.
  Running the workflow by hand only redeploys the tip of `main`.
- **Take the site down:** in the portal, delete the resource group or the Static Web App.
  The URL stops working. The Free plan never bills.
- **Token exposed:** **Manage deployment token → Reset token**, then update the GitHub secret.
- **Stop deploys, keep the site:** **Actions → the workflow → ⋯ → Disable workflow**.

## 6. Cost

The Free plan costs $0, and overage bandwidth isn't available on it. GitHub
Actions is free for public repos. Set a budget alert anyway:
**Cost Management → Budgets → + Add**, monthly, small amount, alerts at 50% and 100%.
The only paid resource in this project is the Foundry model deployment, billed
per token when a script calls it. The site never calls it.
