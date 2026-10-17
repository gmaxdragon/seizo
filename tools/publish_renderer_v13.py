"""Stage a checksum-pinned Windows renderer v13 candidate after all test jobs pass.

Never changes SeizoOfficial or physical motor permissions.
Never reads, moves, trains or exports the user's saved PPO model.
This publishes to the candidate branch only. Stable is a separate step.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import shutil

ROOT=Path(__file__).resolve().parents[1]
BRANCH="seizo-v13-win-render-repair-20261017"
VERSION="2026.10.17-windows-render-v13"
ADDITIONS=("core/main_thread_renderer.py","scripts/check_camera_gl.py")


def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT,text=True).strip()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check_updaters(manifest):
    for name in ("seizo_updater.py","release-legacy-updater.py"):
        spec=importlib.util.spec_from_file_location("updater_check_"+name.replace(".","_"),ROOT/name)
        obj=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obj)
        obj.validated_manifest(manifest)


def verify_install(manifest):
    spec=importlib.util.spec_from_file_location("updater_v13_test",ROOT/"seizo_updater.py")
    updater=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    with tempfile.TemporaryDirectory(prefix="seizo-v13-test-") as temp:
        install=Path(temp)/"Studio"
        sentinel=install/"data"/"camera_views_v9"/"policy.npz"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b"PRIVATE_CHECKPOINT_PRESERVE_TEST_8887")
        log=install/"logs"/"startup.log"
        log.parent.mkdir(parents=True)
        log.write_text("sentinel")
        updater.INSTALL=install
        updater.RELEASE_FILE=install/".seizo_release.json"
        def local_download(url,maximum=3_000_000):
            if url==manifest["base"]["url"]:
                blob=(ROOT/"Seizo_Learn_Web.tar.xz").read_bytes()
            else:
                key="/patches/"
                if key not in url:raise RuntimeError("Unknown update URL")
                filename=url.split(key,1)[1]
                blob=(ROOT/"patches"/filename).read_bytes()
            if len(blob)>maximum:raise ValueError("Local test blob too large")
            return blob
        updater.urlbytes=local_download
        assert updater.update_from_manifest(manifest) is True
        assert sentinel.read_bytes()==b"PRIVATE_CHECKPOINT_PRESERVE_TEST_8887"
        assert log.read_text()=="sentinel"
        assert (install/"core"/"main_thread_renderer.py").is_file()
        assert (install/"scripts"/"check_camera_gl.py").is_file()
        for filename,entry in manifest["patches"].items():
            assert sha((install/filename).read_bytes())==entry["sha256"],filename
        assert updater.current_version()==VERSION
        assert updater.update_from_manifest(manifest) is False
        assert sentinel.read_bytes()==b"PRIVATE_CHECKPOINT_PRESERVE_TEST_8887"


def main():
    if os.getenv("GITHUB_REF")!="refs/heads/"+BRANCH:
        raise RuntimeError("Candidate release only, not stable")
    source=git("rev-parse","HEAD")
    remote=git("ls-remote","origin","refs/heads/"+BRANCH).split()[0]
    if remote!=source:
        raise RuntimeError("Candidate branch advanced while tests ran")

    manifest=json.loads((ROOT/"desktop_manifest.json").read_text())
    assert manifest["schema"]=="seizo-desktop-manifest/v1"
    assert manifest["version"]=="2026.10.16-learning-feedback-v12"
    names=list(manifest["patches"])+list(ADDITIONS)
    assert len(names)==len(set(names)) and len(names)<=80
    manifest["version"]=VERSION
    patches={}
    for name in names:
        path=ROOT/"patches"/name
        if not path.is_file() or path.is_symlink():raise ValueError("Missing source "+name)
        patches[name]={"url":"https://raw.githubusercontent.com/gmaxdragon/seizo/"+source+"/patches/"+name,
                       "sha256":sha(path.read_bytes())}
    manifest["patches"]=patches
    check_updaters(manifest)
    verify_install(manifest)

    (ROOT/"desktop_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    proof={"schema":"seizo-desktop-render-repair-proof/v13","version":VERSION,
           "source_commit":source,"checks":{"windows_dispatch":"passed_workflow_dependency",
                                            "linux_real_RGB":"passed_workflow_dependency",
                                            "original_updater_install":"passed_local_package_test"},
           "patch_count":len(patches),"protected_policy_replaced":False,
           "current_user_policy_inspected":False,
           "native_user_windows_gpu_verified":False,
           "real_pi_connected":False,"automatic_motion_enabled":False,
           "physical_motion_executed":False,
           "note":"Candidate only. Actual Windows GPU framebuffer must pass the local doctor."}
    (ROOT/"release-proof-v13.json").write_text(json.dumps(proof,indent=2)+"\n")
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    subprocess.run(["git","add","desktop_manifest.json","release-proof-v13.json"],cwd=ROOT,check=True)
    subprocess.run(["git","commit","-m","Package pinned v13 Windows main-thread renderer candidate"],cwd=ROOT,check=True)
    subprocess.run(["git","push","origin","HEAD:refs/heads/"+BRANCH],cwd=ROOT,check=True)
    print(json.dumps({"version":VERSION,"packaged_head":git("rev-parse","HEAD"),
                      "source_commit":source,"patches":len(patches),
                      "protected_checkpoint_preservation_test":True}))


if __name__=="__main__":
    main()
