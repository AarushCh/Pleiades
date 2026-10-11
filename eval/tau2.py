from __future__ import annotations

import argparse
import json
import re
import tomllib

from external import EXTERNAL, KS, fetch, isolate, organisation, pct, table, write_kb

DATA = EXTERNAL / "tau2"
BASE = ("https://raw.githubusercontent.com/sierra-research/tau2-bench/"
        "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699/data/tau2/domains/telecom/")
LABELS = {"tech_support_manual.md": "Tech Support Manual", "tech_support_workflow.md": "Troubleshooting Workflow",
          "main_policy.md": "Agent Policy", "plans.md": "Plans"}
PATHS = {"service_issue": ("Cellular Service", "Path 1:"), "mobile_data_issue": ("Mobile Data", "Path 2"),
         "mms_issue": ("MMS", "Path 3:")}
LINE = ({"Line Suspension", "Overdue Bill Payment", "Step 1.4: Check Line Suspension"}, ("suspen", "overdue", "pay"))
FIXES = {
    "toggle_airplane_mode": ({"Airplane Mode", "Step 1.1: Check Airplane Mode and Network Status"}, ("airplane",)),
    "reseat_sim_card": ({"SIM Card Issues", "Step 1.2: Verify SIM Card Status"}, ("sim",)),
    "reset_apn_settings": ({"Incorrect APN Settings", "Verifying APN (MMSC URL) for MMS",
                            "Step 1.3: Try to reset APN settings", "Step 3.6: Check APN Settings"}, ("apn",)),
    "toggle_roaming": ({"Addressing Data Roaming Problems", "Step 2.1.2: Verify if user is traveling"}, ("roaming",)),
    "enable_roaming": ({"Addressing Data Roaming Problems", "Data Roaming",
                        "Step 2.1.2: Verify if user is traveling"}, ("roaming",)),
    "toggle_data": ({"Mobile Data Disabled", "Step 2.1.3: Check Mobile Data Settings",
                     "Step 3.2: Verify Mobile Data Status"}, ("mobile data",)),
    "toggle_data_saver_mode": ({"Data Saver Mode", "Step 2.2.1: Check Data Restriction Settings"}, ("data saver",)),
    "set_network_mode_preference": ({"Optimizing Network Mode Preferences", "Unsuitable Network Technology for MMS",
                                     "Step 2.2.2: Check Network Mode Preference", "Step 3.3: Check Network Technology"},
                                    ("network mode", "5g", "4g", "lte")),
    "disconnect_vpn": ({"VPN Connection Issues", "Step 2.2.3: Check for Active VPN"}, ("vpn",)),
    "toggle_wifi_calling": ({"Investigating Wi-Fi Calling Interference with MMS",
                             "Step 3.4: Check Wi-Fi Calling Status"}, ("wi-fi calling", "wifi calling")),
    "grant_app_permission": ({"Messaging App Lacks Necessary Permissions",
                              "Step 3.5: Verify Messaging App Permissions"}, ("permission",)),
    "refuel_data": ({"Data Plan Limits Reached", "Data Refueling", "Step 2.1.4: Check Data Usage"},
                    ("refuel", "top up", "top-up", "more data", "add data")),
    "make_payment": LINE,
    "send_payment_request": LINE,
    "resume_line": LINE,
    "transfer_to_human_agents": ({"SIM Card Issues", "Step 1.2: Verify SIM Card Status"},
                                 ("human", "person", "technical support", "escalat")),
}


def documents() -> dict[str, str]:
    docs = {name: fetch(BASE + name, DATA / name).read_text(encoding="utf-8") for name in LABELS if name != "plans.md"}
    plans = tomllib.loads(fetch(BASE + "db.toml", DATA / "db.toml").read_text(encoding="utf-8"))["plans"]
    docs["plans.md"] = "# Plans\n\n| Plan | Data per month | Price per month | Extra data |\n|---|---|---|---|\n" + "".join(
        f"| {p['name']} | {p['data_limit_gb']:g} GB | ${p['price_per_month']:.2f} | "
        f"${p['data_refueling_price_per_gb']:.2f} per GB |\n" for p in plans)
    return docs


def cases(split: str) -> list[dict]:
    tasks = json.loads(fetch(BASE + "tasks.json", DATA / "tasks.json").read_text(encoding="utf-8"))
    chosen = set(json.loads(fetch(BASE + "split_tasks.json", DATA / "split_tasks.json").read_text(encoding="utf-8"))[split])
    out = []
    for t in tasks:
        if t["id"] in chosen:
            info = t["user_scenario"]["instructions"]
            known = re.sub(r"You are [^.]*phone number[^.]*\.\s*", "", info.get("known_info") or "")
            out.append({"id": t["id"], "kind": t["id"][1:t["id"].index("]")],
                        "customer": f"{info['reason_for_call']} {known}".strip(), "ticket": t["ticket"],
                        "fixes": sorted({a["name"] for a in t["evaluation_criteria"]["actions"] or [] if a["name"] in FIXES})})
    return out


def headings(doc) -> set[str]:
    return {doc.metadata.get(k, "") for k in ("doc_title", "section", "subsection")}


def score(docs: list, case: dict) -> dict[str, list[float]]:
    heads = [headings(d) for d in docs]
    path = [any(p in d.metadata.get(k, "") for k in ("doc_title", "section") for p in PATHS[case["kind"]])
            for d in docs]
    found = [[any(FIXES[f][0] & hs for hs in heads[:k]) for f in case["fixes"]] for k in KS]
    return {"path": [any(path[:k]) for k in KS],
            "fixes": [sum(f) / len(f) if f else 1.0 for f in found],
            "all": [all(f) for f in found]}


def answers(bot, todo: list[dict]) -> None:
    rows, said, needed = [], 0, 0
    for case in todo:
        reply = bot.answer(case["customer"], remember=False)
        text = reply["answer"].lower()
        hit = [f for f in case["fixes"] if any(w in text for w in FIXES[f][1])
               or (f == "transfer_to_human_agents" and reply["outcome"] == "escalated")]
        said, needed = said + len(hit), needed + len(case["fixes"])
        rows.append([case["id"][:60], reply["outcome"], f"{len(hit)}/{len(case['fixes'])}"])
    table(["task", "outcome", "fixes mentioned"], rows)
    print(f"\nFixes the answer tells the customer to try: {pct(said, needed)}% of {needed}")


def main() -> None:
    parser = argparse.ArgumentParser(description="τ²-bench telecom: does Pleiades surface the fixes each task needs?")
    parser.add_argument("--split", default="base", choices=["base", "train", "test", "small", "full"])
    parser.add_argument("--answers", type=int, default=0,
                        help="also generate answers for this many tasks of the 'small' split (uses the model)")
    args = parser.parse_args()

    isolate(DATA / "work", model=bool(args.answers))
    write_kb(DATA / "work" / "kb", documents())
    bot = organisation("tau2_telecom", "Telecom", LABELS, model=bool(args.answers))
    todo = cases(args.split)
    deep = max(KS)
    for variant in ("customer", "ticket"):
        totals = {m: [0.0] * len(KS) for m in ("path", "fixes", "all")}
        for case in todo:
            for metric, values in score(bot.retrieve(case[variant], [], top_k=deep, expand=False).docs, case).items():
                totals[metric] = [t + v for t, v in zip(totals[metric], values, strict=True)]
        print(f"\nτ²-bench telecom, {args.split} split, {len(todo)} tasks, query = {variant}'s words\n")
        table(["metric", *(f"@{k}" for k in KS)],
              [[{"path": "right troubleshooting path", "fixes": "required fixes retrieved",
                 "all": "every fix retrieved"}[m], *(f"{100 * v / len(todo):.1f}" for v in vals)]
               for m, vals in totals.items()])
    if args.answers:
        print()
        answers(bot, cases("small")[:args.answers])


if __name__ == "__main__":
    main()
