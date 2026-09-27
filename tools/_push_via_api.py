# -*- coding: utf-8 -*-
"""把本地 HEAD 同步到 GitHub（Contents API 版），用于 push 被代理拦截的场合。

为什么需要它：本机 git 装了这样的全局配置

    url.https://ghfast.top/https://github.com/.insteadOf https://github.com/

把 `https://github.com/...` 一律重写成镜像地址，而该镜像**不接受** GitHub
token 认证，于是 `git push` 必然报 "Invalid username or token"。改用 HTTP API
就完全不走那套 URL 改写。

空仓库下 Git Data API（git/blobs）会返回 409 "Git Repository is empty"，
所以这里用 Contents API：它能直接在空仓库上创建第一个文件。

用法：
    GH_TOKEN=$(gh auth token) python tools/_push_via_api.py [--dry-run]

注意：它**逐文件 PUT**，每次都会生成一个提交。只在 git push 走不通时用它；
平时正常的 git push 仍然是首选。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ.get("PUSH_REPO", "Zyvn-coder/python-learning-path")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*a):
    # core.quotepath=false：否则中文文件名会被转义成 \345\205\245… 拿不到真实路径
    return subprocess.run(["git", "-C", ROOT, "-c", "core.quotepath=false"] + list(a),
                          capture_output=True, text=True, check=True).stdout


def show(path):
    return subprocess.run(["git", "-C", ROOT, "show", "HEAD:" + path],
                          capture_output=True, check=True).stdout


def api(path, data=None, method=None):
    tok = os.environ["GH_TOKEN"]
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("https://api.github.com" + path, data=body,
                                 method=method or ("PUT" if body else "GET"))
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "push-via-api")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or b"{}")


def remote_paths():
    """远端已有的文件 → 其 blob sha，用来跳过内容没变的文件。"""
    try:
        t = api("/repos/%s/git/trees/main?recursive=1" % REPO)
    except urllib.error.HTTPError as e:
        if e.code in (404, 409):
            return {}
        raise
    return {x["path"]: x["sha"] for x in t.get("tree", []) if x["type"] == "blob"}


def remote_file_sha(path):
    """取远端某文件的当前 blob sha。

    Contents API **更新**已有文件时必须带 `sha`（要改的那一版的 sha），
    否则回 422 `"sha" wasn't supplied.`。git/trees 给的是 blobs API 的 sha，
    与这里要的不是同一个值，所以得单独问一次 contents 接口。
    """
    try:
        r = api("/repos/%s/contents/%s?ref=main" % (REPO, urllib.parse.quote(path)))
        return r.get("sha")
    except urllib.error.HTTPError:
        return None


def main():
    dry = "--dry-run" in sys.argv
    if not os.environ.get("GH_TOKEN"):
        print("缺 GH_TOKEN。用 `GH_TOKEN=$(gh auth token) python tools/_push_via_api.py`")
        return 2

    files = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    msg = git("log", "-1", "--pretty=%B").strip().splitlines()[0]
    print("本地 HEAD 有 %d 个文件，目标 %s" % (len(files), REPO))

    old = remote_paths()
    print("远端现有 %d 个文件" % len(old))

    n_new = n_same = n_fail = 0
    for i, f in enumerate(files, 1):
        raw = show(f)
        # 内容没变就跳过：避免给每个文件都留一个空提交
        cur_sha, same = None, False
        if f in old:
            try:
                cur = api("/repos/%s/contents/%s?ref=main" % (REPO, urllib.parse.quote(f)))
                cur_sha = cur.get("sha")
                if cur.get("encoding") == "base64":
                    exist = base64.b64decode(cur["content"])
                    same = exist.replace(b"\r\n", b"\n") == raw.replace(b"\r\n", b"\n")
            except urllib.error.HTTPError:
                pass
        if same:
            n_same += 1
            print("  %2d/%d  = %s" % (i, len(files), f))
            continue

        if dry:
            print("  %2d/%d  + %s（dry-run，未上传）" % (i, len(files), f))
            n_new += 1
            continue

        payload = {"message": msg, "branch": "main",
                   "content": base64.b64encode(raw).decode()}
        if cur_sha:
            # 更新已有文件必须带当前 sha，否则 422
            payload["sha"] = cur_sha
        try:
            r = api("/repos/%s/contents/%s" % (REPO, urllib.parse.quote(f)), payload)
            n_new += 1
            print("  %2d/%d  + %s  -> %s" % (i, len(files), f, r["commit"]["sha"][:8]))
        except urllib.error.HTTPError as e:
            n_fail += 1
            print("  %2d/%d  ! %s  失败 %s %s"
                  % (i, len(files), f, e.code, e.read().decode("utf-8", "replace")[:160]))

    print("\n新增/更新 %d，未变 %d，失败 %d" % (n_new, n_same, n_fail))
    if not dry and not n_fail:
        print("完成：https://github.com/" + REPO)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
