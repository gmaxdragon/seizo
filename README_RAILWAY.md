# Seizo Web: simulation-only Railway deployment

This **public source branch** contains only Seizo simulator code and generated arm meshes, **no API keys** or personal photos. The running Railway site is protected by a password.

The Python simulator is in `Seizo_Learn_Web.tar.xz`, SHA256 `4d639563b67233f68733c57915f7c5aec4568b6a929cd3ff9e7e39112b04da28`.

**Known issue:** the simulator still uses approximate contact and can allow objects to intersect the arm. Hosting it is not a collision-physics fix. The uploaded MK2 Plus STL and modified gripper linkage are not yet integrated into collision simulation. Do not use this site to issue commands to the real robot.

## Railway deployment

Current service source: public Docker image `python:3.11-slim`.

Start command:

```sh
python -c "import urllib.request; exec(urllib.request.urlopen('https://raw.githubusercontent.com/gmaxdragon/seizo/seizo-railway-host/railway_bootstrap.py',timeout=30).read().decode())"
```

The bootstrap verifies bundle+host checksums, installs NumPy and serves the private simulator. This keeps the app independent from the live Pi. Changes to the branch require Railway restart/redeploy; a simple commit alone does not redeploy a Docker-image source.

If Railway's GitHub App is granted access to this repository, alternatively connect the `seizo-railway-host` branch directly. Then the provided Dockerfile and railway.json support automatic deployment on pushes.

Railway Variables:
- `SEIZO_WEB_PASSWORD`: required, 16+ characters; **never commit or paste into GitHub**.
- `SEIZO_WEB_USERNAME`: `seizo`.
- `SEIZO_ALLOWED_HOSTS`: Railway-generated hostname, without protocol.
- `SEIZO_DATA_DIR`: `/data`.
- `HACKCLUB_API_KEY`: optional. Keep in Railway Variables if used; not embedded in public source or HTML.
- `PORT`: Railway supplies.

Attach a persistent Railway volume at `/data` to preserve saved neural checkpoints.

Railway usage may incur charges after credits. Do not run an unattended million-episode training job without monitoring resources and credits.
