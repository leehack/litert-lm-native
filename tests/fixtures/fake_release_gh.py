#!/usr/bin/env python3
import hashlib, json, os, sys
from pathlib import Path

p = Path(os.environ["FAKE_STATE"])
s = json.loads(p.read_text())
a = sys.argv[1:]
s["calls"].append(a)


def save():
    p.write_text(json.dumps(s))


def out(value, status=200):
    save()
    if "--include" in a:
        print("HTTP/2 " + str(status) + " Status\nContent-Type: application/json\n")
    print(json.dumps(value))
    sys.exit(0 if status < 400 else 1)


if a[:2] == ["release", "create"]:
    s["release"] = s["template"].copy()
    s["release"]["assets"] = []
    save()
    print("draft-created")
    sys.exit(0)
if a[:2] == ["release", "edit"]:
    if s.get("fail_promotion"):
        s["fail_promotion"] = False
        save()
        sys.exit(1)
    s["release"]["draft"] = False
    s["release"]["html_url"] = (
        "https://github.com/leehack/litert-lm-native/releases/tag/"
        + s["release"]["tag_name"]
    )
    save()
    sys.exit(0)
if a[:2] == ["release", "upload"]:
    if "--clobber" not in a:
        s["release"]["assets"] = []
    for raw in a[5:]:
        if raw == "--clobber":
            continue
        f = Path(raw)
        data = f.read_bytes()
        s["release"]["assets"] = [
            x for x in s["release"]["assets"] if x["name"] != f.name
        ]
        aid = s.get("next_id", 0) + 1
        s["next_id"] = aid
        s.setdefault("asset_data", {})[str(aid)] = data.decode()
        s["release"]["assets"].append(
            dict(
                id=aid,
                name=f.name,
                state="uploaded",
                size=len(data),
                digest="sha256:" + hashlib.sha256(data).hexdigest(),
                url="repos/leehack/litert-lm-native/releases/assets/" + str(aid),
            )
        )
    save()
    sys.exit(0)
endpoint = next((x for x in a if x.startswith("repos/")), "")
if "/releases?per_page=" in endpoint:
    s["lists"] = s.get("lists", 0) + 1
    if s.get("mutate_after_readback") and s.get("tag_reads", 0) >= 2:
        s["release"][s["mutate_after_readback"]] = "changed"
    if "--jq" in a:
        save()
        print(s["release"]["id"] if s["release"] else "")
        sys.exit(0)
    out([[s["release"]] if s["release"] else []])
if "/git/ref/tags/" in endpoint:
    s["tag_reads"] = s.get("tag_reads", 0) + 1
    if s.get("get_status"):
        out({"message": "Not Found"}, s["get_status"])
    if s.get("get_malformed"):
        save()
        print("HTTP/2 404 Not Found\n\nnot-json")
        sys.exit(1)
    if s.get("get_transport"):
        save()
        sys.exit(1)
    if s.get("ref_changes") and s["tag_reads"] >= 2:
        s["ref"]["object"]["sha"] = "c" * 40
    if s["ref"] is None:
        out({"message": "Not Found"}, 404)
    out(s["ref"])
if endpoint.endswith("/git/refs"):
    payload = json.load(sys.stdin)
    s["create_payload"] = payload
    if s.get("create_applies", True):
        s["ref"] = {
            "ref": payload["ref"],
            "object": {"type": "commit", "sha": payload["sha"]},
        }
    status = s.get("create_status", 201)
    if s.get("create_transport"):
        save()
        sys.exit(1)
    if s.get("create_bad_response"):
        out({"ref": "bad"}, 201)
    out(s["ref"] if status == 201 else {"message": "uncertain"}, status)
if "/releases/assets/" in endpoint and "-H" in a:
    save()
    sys.stdout.write(
        s["receipt_text"]
        if "receipt_text" in s
        else s["asset_data"][endpoint.rsplit("/", 1)[1]]
    )
    sys.exit(0)
if "/releases/assets/" in endpoint:
    aid = int(endpoint.rsplit("/", 1)[1])
    s["release"]["assets"] = [x for x in s["release"]["assets"] if x["id"] != aid]
    out({})
if "/releases/" in endpoint:
    out(s["release"])
raise SystemExit("unhandled fake gh " + repr(a))
