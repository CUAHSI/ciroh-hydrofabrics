# Pipelines Quickstart (Fork + Demo/DevCon + DVC + Push)

This guide shows how to:
- Fork the repository
- Run the demo/devcon pipeline
- Configure a DVC remote
- Commit updated DVC files
- Push data to DVC remote and code to your Git fork

## 1) Fork and clone

1. Fork this repository on GitHub.
2. Clone your fork locally:

```bash
git clone git@github.com:<your-username>/ciroh-hydrofabrics.git
cd ciroh-hydrofabrics
```

## 2) Create and activate environment

Use your project’s standard environment setup (for example conda/venv + project dependencies).

Example (replace with project-specific commands if different):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install dvc-s3
```

## 3) Configure DVC remote

Using HydroShare as a remote:
- Create a Hydroshare resource
- Get the resource id from the url
    - `https://hydroshare.org/resource/{resource_id}`
- Use the `resource_id` with the swagger api at https://hydroshare.org/hsapi to retrieve the S3 path to the resource.
![Get S3 path to a hydroshare resource](images/openapi-hs-s3-path.png)

```bash
dvc remote add -d myremote <s3://s3.hydroshare.org/{bucket}/{prefix}> 
dvc remote modify myremote profile hydroshare
```

Or use another storage mechnaism for remote storage

Examples for `<remote-url>`:
- S3: `s3://my-bucket/ciroh-hydrofabrics`
- Azure Blob: `azure://my-container/ciroh-hydrofabrics`
- GCS: `gs://my-bucket/ciroh-hydrofabrics`

If credentials are needed, configure them per your backend/provider.

## 4) Run the demo/devcon pipeline

From repository root, run the demo/devcon pipeline:

```bash
dvc repro pipelines/demo/devcon/dvc.yaml
```

## 5) Review and commit updated DVC metadata

After pipeline execution, check changed files:

```bash
git status
```

Typical files to commit:
- `dvc.lock`
- `*.dvc`

Commit changes:

```bash
git checkout -b demo/remote-demo-devcon-dvc
git add dvc.lock dvc.yaml **/*.dvc
git commit -m "Update demo/devcon pipeline outputs and DVC metadata"
```

> If your shell does not expand `**/*.dvc`, add files explicitly or use `find`.

## 6) Push data/artifacts to DVC remote

```bash
dvc push
```

## 7) Push code to your fork

```bash
git push -u origin demo/update-demo-devcon-dvc
```

## 8) Collaborate

Give read or write access to the remote for a collaborator. With HydroShare, open the manage access panel and give approriate access to collaborators or a group of collaborators.

Collaborators will clone your repsoitory and the pipeline cache will be downloaded from your dvc remote.
```bash
dvc repro pipelines/demo/devcon/dvc.yaml
```
