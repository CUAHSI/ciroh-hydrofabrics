# Publishing project docs and notebooks via CIROH DocuHub (now CIROH Hub) and HydroShare

Research note for Jira **CAM-1558**. All sources were accessed on **2026-11-04**
unless a commit SHA is given. Inferences are labelled; unverified items are listed
at the end of each section and under "Could not verify".

## Question

What do CIROH DocuHub (docs.ciroh.org) and HydroShare require for publishing CIROH
project documentation and code notebooks? This covers:

- content format and repo layout
- the contribution and review process, including who approves and how long it takes
- where notebooks are expected to run: the CIROH 2i2c JupyterHub or the HydroShare / CUAHSI JupyterHub, and the "Open with" integrations
- how the CIROH Portal (portal.ciroh.org) fits, if at all

These facts feed a later decision ("Documentation and training Epics") that must turn milestone **M4**, "Publication of
project documentation via DocuHub and HydroShare resources as training materials",
into a checkable "complete when" criterion.

## Summary

- **DocuHub no longer exists as a separate site.** `docs.ciroh.org` and
  `portal.ciroh.org` both show a redirect page: "CIROH Portal and DocuHub have been
  merged into CIROH Hub". The live site is **https://hub.ciroh.org**. The old DocuHub repo
  (`CIROH-UA/ciroh-ua_website`) and the old portal repo (`CIROH-UA/ciroh-portal`) are
  **archived**. The current source is **`CIROH-UA/ciroh_hub`** (Docusaurus, MDX).
  M4's wording ("DocuHub") is out of date.
- **CIROH Hub accepts two kinds of content:**
  - Docs pages: MDX in `docs/products/<category>/<product>/`, contributed by PR. A new product
    can also be requested through a GitHub issue template.
  - Portal listings for notebooks, courses, datasets, apps, presentations, and events: these
    are **not authored in the Hub repo**. They are pulled live from HydroShare by keyword
    tag (`ciroh_hub_notebook`, `ciroh_hub_module`, etc.).
- **Hub review:** an admin/maintainer reviews and merges each PR. No SLA is documented.
  Recent PRs merged anywhere from the same day to about 8 weeks after opening. Merged
  content goes to `hub.ciroh.org/staging/main` right away. It reaches production only when
  a maintainer manually triggers a release. Recent releases came every ~2–8 weeks.
- **HydroShare "Public" and "Published" are different states.** Public resources are
  discoverable and editable, with no DOI. Published resources get a DOI after a light
  CUAHSI staff metadata review, which happens "within business hours". After publication,
  **content, title, and authorship are frozen**. A collection gets a DOI only if every
  member resource is published first.
- **Minimum metadata for a HydroShare DOI:**
  - title of at least 30 characters
  - abstract of at least 150 characters
  - at least 3 keywords, including a geographic one
  - a completed user profile
  - agreement to the publication agreement
  - a README (`README.md` or `README.txt`); the help pages list it as both recommended and required
- **Two JupyterHubs** can launch HydroShare notebooks through **"Open with"**:
  - **CIROH-2i2c JupyterHub** (Google Cloud; free to CIROH consortium members). Access
    requires CIROH affiliation, a GitHub account, and a request filed **by the project PI**
    through a GitHub issue form. Server sizes go up to 52 GB / 16 CPU, and a NextGen/NWM image exists.
  - **CUAHSI JupyterHub** (free). It requires a HydroShare account and membership in the
    CUAHSI JupyterHub HydroShare group.
- **Existing precedent:** a HydroShare tutorial resource with a DOI covers HydroFabric,
  AORC, and NextGen on the CIROH-2i2c hub. The Hub's 2i2c docs point to it. It is the closest
  existing example of what O6/O3 deliverables could look like.
- **CIROH Portal** (the Tethys/HydroShare "research portal") has been folded into the Hub's
  Apps, Datasets, Courses, Presentations, and Notebooks pages. It is not a separate
  publishing target any more.

## DocuHub (now CIROH Hub)

### What changed

| Item | Finding | Source |
|---|---|---|
| docs.ciroh.org | Root URL serves a redirect notice to CIROH Hub | [1] |
| portal.ciroh.org | Same redirect notice | [2] |
| Old DocuHub repo | `CIROH-UA/ciroh-ua_website` is archived (last push 2026-03-27). `CIROH-UA/docuhub-staging` is also archived | [3] |
| Old portal repo | `CIROH-UA/ciroh-portal` is archived (last push 2026-03-27) | [3] |
| Current repo | `CIROH-UA/ciroh_hub`, created 2026-01-26, homepage hub.ciroh.org, MIT license. Latest commit inspected: `dd871fdde97267d9b110acf55f0922a8affc973b` (2026-10-30) | [3][4] |
| Sub-path sites | Org GitHub Pages projects are still served under `docs.ciroh.org/<repo>/`. Example: `docs.ciroh.org/training-HydroShare-101/` renders a Carpentries Workbench lesson (still template content) | [5] |

### Format and repo layout

- **Engine:** Docusaurus with MDX pages. A local build needs Node LTS, `npm install`, and
  `npm run build` / `npm run start` [4][6].
- **Top-level layout (at `dd871fd`):** `docs/` (with `policies/`, `products/`,
  `publications/`, `services/`), `blog/`, `release-notes/`, `src/` (React components and
  pages), `static/`, `docusaurus.config.js`, `sidebars.js` [7].
- **Product docs** live in `docs/products/<category>/<product>/index.mdx`. The existing
  categories are `chpt`, `community-fim`, `data-management`, `evaluation`, `hub-meta`,
  `ml-ai`, `mobile-apps`, `ngiab-ecosystem`, `snow-tools`, and `visualization` [8].
  New categories are agreed with the Community Resources Working Group [9].
- **A page can be thin and pull its content from the project repo.** For example,
  `community-fim/fimbox/index.mdx` contains only front matter plus
  `<GitHubReadme username="sdmlua" repo="fimbox" />`, so the project README is rendered
  inside the Hub [10]. A `GitHubWikiPage` component also exists [11]. With this pattern,
  O5.1/O5.2 docs could stay in `CUAHSI/ciroh-hydrofabrics` and be surfaced on the Hub.
- **Front matter conventions:** `sidebar_position`, `title`, `description`, and `tags` [10][12].
- **Services docs** live in `docs/services/` and cover the 2i2c, CUAHSI, and HydroShare
  pages. These are infrastructure pages, not project pages [13].

### Contribution and review process

- **Minor edits:** click "Edit page" on the live site, which opens a PR; "an admin will
  review and merge" [6].
- **Major edits:** fork, change, open a PR; "an admin will review and merge it", and
  GitHub Actions publishes the result [6]. CONTRIBUTING asks contributors to follow
  existing style and states that contributions are released under the MIT license [14].
- **New product:** open a GitHub issue using the "Add New Product" template [15][9]. It asks for:
  - name and short description
  - category; options include *Geospatial Tools* and *Data Resources*
  - tags
  - at least one link (GitHub repo, documentation URL, HydroShare URL)
  - a primary contact
- **PR template:** a long checklist covering scope, tests, a browser/accessibility check,
  and a CHANGELOG entry. Recent PRs often leave most items unchecked, so it does not
  appear to be strictly enforced (inference) [16][17].
- **Who approves:** the "CIROH Hub team" or "admin team" [4][9]. Reviewers requested on
  recent PRs include `arpita0911patel`, `benlee0423`, `romer8`, `Sheargrub`, and
  `James-Dolinar` [17]. No CODEOWNERS file or named approver policy was found.
- **Staging preview:** a maintainer must add the `preview on staging` label. The PR then
  builds to `hub.ciroh.org/staging/<PR#>` [4][18].
- **How long:**
  - **Review:** no SLA is documented. In the 25 most recent closed PRs (Aug–Oct 2026),
    open-to-merge times ranged from minutes to roughly 8 weeks (e.g. #190: 2026-09-02 → 10-29; #199: 09-30 → 10-22;
    #179: 08-26 → 08-27) [17].
  - **Go-live:** merging to `main` updates `hub.ciroh.org/staging/main` only. Production
    `hub.ciroh.org` changes "only when a new production release is triggered via a
    workflow call" [18]. Recent production releases: 2026-06-15, 06-29, 07-02, 08-26,
    08-28, 08-31, 09-01, 09-14, 09-17, 10-30 [19]. **Merged ≠ live**; the gap can be
    weeks.

### Comparable CIROH project pages

- **NGIAB ecosystem:** `docs/products/ngiab-ecosystem/` is a multi-page product section [8].
- **Community FIM:** `docs/products/community-fim/` holds one thin page per tool, each embedding
  the tool's GitHub README (FIMbox, FIMserv, FIMeval, FIMbench) [10][20].
- **DataStreamCLI / ForcingProcessor:** each GitHub repo's homepage points at its Hub docs
  page, e.g. `.../docs/products/research-datastream/datastreamcli/` [3].
- **HydroShare product page:** `docs/products/data-management/hydroshare/index.mdx` has
  sections for overview, technologies, access, code, issues, team, and citation [12]. It is a
  reasonable template for an O5.1-style page.
- **Training modules:** `CIROH-UA/training-NGIAB-101` and `training-HydroShare-101` are
  standalone Carpentries Workbench lessons. They are published on GitHub Pages under
  `docs.ciroh.org/<repo>/`, not inside the Hub repo [3][5][21].

## HydroShare

### Resource types and collections

- **Resource:** HydroShare's unit of sharing. It is file-agnostic and holds any file
  type. It supports content types such as Single File, CSV, Geographic Feature/Raster,
  Multidimensional, Model Program/Instance, Time Series, and File Set [22].
- **Collection:** a resource that lists other resources. Two rules apply [23]:
  - A collection that contains private resources cannot be made public or published.
  - Other users can add your resource to their collections only if it is marked "Shareable".
- **Sharing states:** Private, Discoverable, Public, and Published [24][23].
- **Quota and size:** the default quota is 20 GB per user. Users can request more. CIROH
  guidance recommends HydroShare for datasets **under 5 GB** and advises against very
  large or rapidly changing datasets [25][12].
- **Groups and communities:** resources shared with a group in the **CIROH community**
  (`hydroshare.org/community/4`) appear on that community page. The Hub's guidance says
  they also appear on the Hub [13]. Groups cannot own resources.

### How resources reach CIROH Hub

- **Tags:** the Hub portals pull resources by **keyword tag** [9][26]:
  - `ciroh_hub_notebook` → Notebooks page
  - `ciroh_hub_module` → Courses page
  - `ciroh_hub_data` → Datasets page
  - `ciroh_hub_app` → Apps page
  - `ciroh_hub_presentation` → Presentations page
  - `ciroh_hub_event` → Events page

  The older `nwm_portal_*` and `ciroh_portal_*` tags still work but are deprecated.
- **Optional extended metadata:** `page_url`, `docs_url`, `thumbnail_url`, and `pres_path` [26].
- **Retrieval:** the site queries HydroShare's discovery-atlas search API from the browser
  by keyword. It also merges in resources from the CIROH community's groups [27]. *Inference:*
  because these calls are unauthenticated, only Public (or Discoverable) resources will
  appear.
- **Featured items** are curated. A resource is featured by adding it to a specific
  Hub-owned HydroShare collection. This is not self-service [9][26].
- **Creation form:** the Hub has a "Create a CIROH HydroShare Resource" form that uses
  HydroShare OAuth and pre-fills the required tags [9][28].

### Formal publication (DOI) and its constraints

- **Steps** [29]:
  1. Make the resource public.
  2. Complete your HydroShare profile.
  3. Click "Publish". The dialog checks minimum metadata.
  4. Accept the HydroShare publication agreement.
  5. Submit.
- **Review:** after submission, "a light review by a member of CUAHSI staff" checks
  metadata and community guidelines. Requests are "reviewed within business hours".
  Requests submitted after hours on Friday are reviewed Monday [30]. DOI registration "may
  take a little time" after acceptance [29].
- **Minimum metadata** [30]:
  - title of at least 30 characters
  - abstract of at least 150 characters
  - at least 3 subject keywords, including geographic location keywords
- **Recommended metadata** [30]:
  - funding agency
  - geographic coverage
  - a README (`README.md` / `README.txt`); the same page also says a README "must be included"
- **Immutability after publication** [31]:
  - **Cannot change:** content files, title, authorship.
  - **Can change:** abstract, most keywords, coverage, references, related resources, credits, and contributors.
  - Larger corrections go through help@cuahsi.org. A mistaken publication can be deleted and
    its DOI disassociated by an admin [29].
- **Collections:** a collection gets a DOI only if **every member resource is already
  published** [24][23][29].
- **What cannot be published:** web app connectors [24].
- **DOI form:** `https://doi.org/10.4211/hs.<resource_id>` [29].

### Notebook launching from HydroShare ("Open with")

- The "Open with" menu on a resource landing page lists approved apps. Both **CIROH
  JupyterHub (2i2c)** and **CUAHSI JupyterHub** appear there [32][33][34].
- **CIROH-2i2c behaviour** [33]:
  - The resource's files are copied to `Downloads/<resource GUID>` in the user's
    JupyterHub home. Edits do not change the HydroShare resource.
  - Work can be pushed back with the **hsfiles_jupyter** extension (right-click
    upload/replace/delete/status/download) or with **hsclient**.
- **CUAHSI behaviour:** "a computing environment will be prepared and the content of the
  current HydroShare resource will be placed inside of it" [34].
- **Precedent notebook resource:** *Working with HydroShare, AORC data, HydroFabric and
  NextGen on CIROH-2i2c JupyterHub Tutorial*, DOI 10.4211/hs.fc8539358fe64ca6a47468728a0687a1.
  It was written specifically for this integration [33].

## Where notebooks run

| | CIROH-2i2c JupyterHub | CUAHSI JupyterHub |
|---|---|---|
| URL | `ciroh.awi.2i2c.cloud` (prod), `staging.ciroh.awi.2i2c.cloud` | `jupyterhub.cuahsi.org` |
| Host / cost | 2i2c on Google Cloud; "free to use for consortium members", paid by CIROH Infrastructure funds [35] | CUAHSI; "free cloud computing environment" [34] |
| Login | GitHub OAuth ("AWI CIROH prod" app) [33] | HydroShare credentials [34] |
| Eligibility | CIROH affiliation required. The **PI** submits a Cloud Infrastructure Request Form (GitHub issue in `CIROH-UA/NGIAB-CloudInfra`) listing team GitHub usernames and CPU/GPU needs; the UA team reviews it [36][32] | Request to join the CUAHSI JupyterHub HydroShare group; admission is granted by CUAHSI; a complete HydroShare profile speeds it up [34][37] |
| Compute | Small 5 GB/2 CPU through Huge 52 GB/16 CPU; GPU available; 250 GB per-user storage [35] | Selectable "profile environments"; specs not checked here |
| Software | Images from `CIROH-UA/awi-ciroh-image` (Pangeo base, NextGen/NWM image with NextGen and preprocessors). Custom packages are requested via a GitHub issue [35][33] | CUAHSI-maintained profiles (not inspected) |
| "Open with" | Yes [32][33] | Yes [34] |
| Workshops | A separate workshop hub is active only during events. Requests go through the Workshop IT Request Form [35][38] | Not documented here |

**Trade-offs (facts, not a recommendation):**

- **CIROH-2i2c:**
  - *For:* larger and GPU-capable machines; NextGen tooling preinstalled; existing
    HydroFabric/NextGen tutorial precedent.
  - *Against:* restricted to CIROH-affiliated users approved through a PI-filed request, so
    community users outside CIROH cannot run the notebooks there.
- **CUAHSI:**
  - *For:* any HydroShare user can request access (inference from the stated process).
  - *Against:* access still needs group admission; its environments may not include
    hydrofabric/NextGen dependencies (not verified).
- **Both:** HydroShare is the shared launch point, so one resource can offer both targets
  through "Open with" without duplicating content.

## CIROH Portal

- `portal.ciroh.org` redirects to CIROH Hub [2]. The `CIROH-UA/ciroh-portal` repo
  (described as "CIROH Portal for products, publications and courses") is archived [3].
- The portal's functions now live in CIROH Hub:
  - HydroShare-backed Apps, Datasets, Courses, Presentations, and Notebooks pages
  - Zotero-backed Publications page

  The Hub's meta-docs call these "research portals" [26][9].
- A separate Tethys app portal still exists: `CIROH-UA/tethysportal-ciroh`, with commits as
  recent as 2026-11-03. The Hub's Apps page advertises a "CIROH Tethys Portal" [3][17]. It
  is relevant only if the project ships a web app (e.g. the `subsetter/` app). It is not a
  docs or notebook venue. Apps reach the Hub's Apps page through the `ciroh_hub_app` tag.

## Implications for defining M4 "published"

These are facts and options only. No decision is made here.

**Facts the definition must accommodate**

1. "DocuHub" now means **CIROH Hub (hub.ciroh.org)**. A criterion that names docs.ciroh.org
   would point at a redirect.
2. Hub publication involves two separate gates outside the project's control:
   - **PR merge** by the Hub team (no SLA; same day to weeks)
   - **production release** (manual; every ~2–8 weeks)

   "Merged to `main`" and "visible on hub.ciroh.org" are different, separately checkable states.
3. HydroShare-backed Hub listings need only a correctly tagged resource that the
   discovery API can see. No Hub PR or approval is needed. *Featured* status requires
   curation by the Hub team.
4. A HydroShare DOI needs CUAHSI review (business hours) and **freezes** content, title,
   and authorship. Notebooks that keep evolving would need new resources/DOIs, or would
   stay "Public" rather than "Published".
5. Running notebooks on CIROH-2i2c depends on a PI-filed access request and CIROH
   affiliation. Running on CUAHSI depends on group admission.

**Candidate "complete when" formulations**, combinable and ordered from least to most demanding:

- **A. Discoverable on CIROH Hub**
  - A project docs page (MDX, possibly embedding this repo's README) is merged into
    `CIROH-UA/ciroh_hub` and present in a production release tag.
  - The O6/O3 HydroShare resources are Public, tagged `ciroh_hub_notebook` /
    `ciroh_hub_module`, and appear on hub.ciroh.org/notebooks or /courses.
  - Evidence: PR URL, release tag, resource URLs.
- **B. A + citable**
  - Training and use-case resources, or a HydroShare collection of them, are formally
    published with DOIs.
  - Evidence: DOIs resolve. Constraints: immutability, and every collection member must be published.
- **C. A or B + executable**
  - Each notebook resource has been launched via "Open with" on a named hub (CIROH-2i2c
    and/or CUAHSI) and run end to end.
  - Evidence: a recorded run date and image/environment per notebook.
- **D. Coverage clause** (attachable to A–C)
  - Every listed output has a home: O5.1 technical docs, O5.2 user docs/guidelines, O6
    training notebooks and markdown, O3 use-case notebooks.
  - Each home is a named Hub page or a named HydroShare resource.

**Questions the decision will need to settle**

- Do O5.1/O5.2 docs live in this repo and get embedded into the Hub, or get authored as MDX in `ciroh_hub`?
- Which Hub category fits: `data-management`, `ngiab-ecosystem`, or a new one?
- Is a DOI required, or is "Public + tagged" enough?
- Which JupyterHub is the reference runtime, given who the training audience is?
- Should M4 depend on external review/release timing, or only on "submitted" states (PR opened, publication requested)?

## Could not verify

- Whether Hub portal listings ever include non-Public resources. The note infers they do
  not, based on unauthenticated API calls [27].
- Turnaround for CIROH-2i2c access approval and for CUAHSI JupyterHub group admission.
  Neither is documented.
- Exact HydroShare DOI turnaround beyond "reviewed within business hours". The
  publication agreement text and licence requirements were not read.
- The CUAHSI JupyterHub environment contents and whether hydrofabric/NextGen dependencies
  are present.
- The live Tethys portal URL; it was not confirmed.
- Whether the Hub team requires anything beyond the issue/PR templates (e.g. a
  Working Group presentation) before accepting a new product page. Nothing found says so.
- The docs.ciroh.org "Edit this page" links. They were not checked, because the root now
  redirects and the archived repo is read-only.

## Sources

All accessed 2026-11-04.

1. https://docs.ciroh.org/ (redirect notice to CIROH Hub)
2. https://portal.ciroh.org/ (redirect notice to CIROH Hub)
3. GitHub API, CIROH-UA org repos sorted by push: https://api.github.com/orgs/CIROH-UA/repos?sort=pushed (archived flags, descriptions, homepages)
4. `CIROH-UA/ciroh_hub` README @ `dd871fd`: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/README.md
5. https://docs.ciroh.org/training-HydroShare-101/
6. Hub meta-docs "Getting Started": https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/products/hub-meta/getting-started.mdx
7. Repo root listing: https://api.github.com/repos/CIROH-UA/ciroh_hub/contents/
8. `docs/products` tree: https://api.github.com/repos/CIROH-UA/ciroh_hub/git/trees/b60721cffb1e1824406c96a7aadb5faa6c0dbaea
9. Hub Contribute page: https://hub.ciroh.org/contribute
10. FIMbox page: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/products/community-fim/fimbox/index.mdx
11. `src` tree (GitHubReadme, GitHubWikiPage, HydroShare components): https://api.github.com/repos/CIROH-UA/ciroh_hub/git/trees/daa8696d6a64b3909b28e0465a94424472708b8a?recursive=1
12. HydroShare product page: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/products/data-management/hydroshare/index.mdx
13. Hub HydroShare service page: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/services/cloudservices/HydroShare/index.mdx
14. CONTRIBUTING.md: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/CONTRIBUTING.md
15. Product request issue template: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/.github/ISSUE_TEMPLATE/product-request.md
16. PR template: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/.github/PULL_REQUEST_TEMPLATE.md
17. Recent closed PRs: https://api.github.com/repos/CIROH-UA/ciroh_hub/pulls?state=closed&per_page=30
18. Hub meta-docs "CI/CD": https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/products/hub-meta/ci-cd.mdx
19. Hub releases: https://api.github.com/repos/CIROH-UA/ciroh_hub/releases
20. Community FIM tree: https://api.github.com/repos/CIROH-UA/ciroh_hub/git/trees/7314094ceae55478e85432226e3840a8d53bd746?recursive=1
21. training-HydroShare-101 README: https://raw.githubusercontent.com/CIROH-UA/training-HydroShare-101/main/README.md
22. HydroShare help index (content types nav): https://help.hydroshare.org/
23. HydroShare help, Collections: https://help.hydroshare.org/hydroshare-resources/collections/
24. HydroShare help, Publishing in HydroShare: https://help.hydroshare.org/publishing-in-hydroshare/
25. HydroShare help, CIROH on HydroShare: https://help.hydroshare.org/introduction-to-hydroshare/ciroh-on-hydroshare/
26. Hub meta-docs "HydroShare Portals": https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/products/hub-meta/hydroshare-portals.mdx
27. HydroShareImporter source: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/src/components/HydroShare/HydroShareImporter/index.js ; Notebooks page: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/src/pages/notebooks/index.js
28. PR #191 "Add HydroShare resource creation form": https://github.com/CIROH-UA/ciroh_hub/pull/191
29. HydroShare help, How to Publish and Receive a DOI: https://help.hydroshare.org/publishing-in-hydroshare/how-to-publish-in-hydroshare/
30. HydroShare help, Minimum Metadata Requirements: https://help.hydroshare.org/publishing-in-hydroshare/minimum-metadata-requirements-for-publishing-in-hydroshare/
31. HydroShare help, Limited Editing on Published Resources: https://help.hydroshare.org/publishing-in-hydroshare/limited-editing-on-published-resources/
32. HydroShare help, CIROH Jupyterhub: https://help.hydroshare.org/apps/ciroh-jupyterhub/
33. Hub 2i2c HydroShare Integration: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/services/cloudservices/2i2c/hydroshare-integration.mdx
34. Hub CUAHSI JupyterHub page: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/services/cloudservices/cuahsi/index.mdx
35. Hub CIROH-2i2c JupyterHub page: https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/docs/services/cloudservices/2i2c/index.mdx
36. Hub access component (JupyterHub): https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/src/components/InfrastructureAccess/CIROHJupyterHub.js
37. CUAHSI JupyterHub getting started: https://raw.githubusercontent.com/CUAHSI/jupyterhub/main/docs/getting-started.md
38. Hub access component (Workshops): https://raw.githubusercontent.com/CIROH-UA/ciroh_hub/main/src/components/InfrastructureAccess/WorkshopSupport.js
