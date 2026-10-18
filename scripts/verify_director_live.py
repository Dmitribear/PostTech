"""Verify the director role using marked synthetic accounts; restore original role."""

import json

from verify_live_workflow import API, ROOT, read_json, require, now


def run(base="http://127.0.0.1:8000"):
    accounts = read_json(ROOT / ".local/scenario-credentials.json")
    api = API(base)
    profiles = {}
    for actor in ("hr", "director", "manager", "employee"):
        account = accounts[actor]
        require(
            account["email"].endswith("@posttech.demo"), "Synthetic account required"
        )
        auth = api.call(
            "POST", "/auth/login", body={k: account[k] for k in ("email", "password")}
        )
        api.tokens[actor] = auth["access_token"]
        profile = api.call("GET", "/profile", actor)
        require(
            profile["external_source"] == "posttech-scenario-check"
            and profile["id"] == account["profile_id"],
            "Fixture identity mismatch",
        )
        profiles[actor] = profile
    target = profiles["director"]
    path = f"/admin/employees/{target['id']}/role"
    api.call("PATCH", path, "employee", {"role": "director"}, expected=403)
    changed = False
    try:
        api.call("PATCH", path, "hr", {"role": "director"})
        changed = True
        require(
            api.call("GET", "/profile", "director")["role"] == "director",
            "Role not effective",
        )
        route = api.call("GET", "/requests/routing", "director")
        require(
            route["route"] == "hr"
            and all(p["id"] != target["id"] for p in route["approvers"]),
            "Director self-approval route",
        )
        team = api.rows("/team", "director")
        require(
            any(p["id"] == profiles["manager"]["id"] for p in team),
            "Direct report missing",
        )
        require(
            not any(p["id"] == profiles["employee"]["id"] for p in team),
            "Indirect report leaked",
        )
        api.call("GET", "/admin/employees", "director", expected=403)
    finally:
        if changed:
            api.call("PATCH", path, "hr", {"role": target["role"]})
            require(
                api.call("GET", "/profile", "director")["role"] == target["role"],
                "Original fixture role was not restored",
            )
    return {
        "status": "passed",
        "checked_at": now(),
        "checks": [
            "hr_assigns_director",
            "worker_cannot_assign",
            "director_team_scope",
            "director_is_not_hr",
            "own_request_routes_to_hr",
            "fixture_role_restored",
        ],
    }


if __name__ == "__main__":
    try:
        result = run()
        (ROOT / ".local/director-live-report.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1)
