"""Interactive network view (pyvis, assets inlined: no CDN) built from an evidence pack."""
from __future__ import annotations

from pyvis.network import Network

COLORS = {
    "individual": "#3b82f6", "watchlisted": "#dc2626", "device_fingerprint": "#f59e0b", "phone": "#a855f7",
    "email": "#ec4899", "address": "#10b981", "account": "#64748b", "entity": "#0ea5e9", "sanctioned": "#dc2626",
    "other_id": "#8b5cf6", "subject": "#111827",
}
LINK_LABEL = {"device_fingerprint": "device", "phone": "phone", "email": "email", "address": "address"}


def _net(height: int) -> Network:
    net = Network(height=f"{height}px", width="100%", bgcolor="#ffffff", font_color="#111827", cdn_resources="in_line", directed=False)
    net.set_options("""{"physics": {"barnesHut": {"gravitationalConstant": -6000, "springLength": 120}, "stabilization": {"iterations": 150}},
                        "interaction": {"hover": true, "navigationButtons": false}, "edges": {"smooth": false}}""")
    return net


def identity_network(ev: dict, labels: dict[str, str] | None = None, height: int = 560) -> str | None:
    netb = ev.get("network") or {}
    members = netb.get("members") or []
    if not members:
        return None
    labels = labels or {}
    listed = {w["subject_id"]: w["list_type"] for w in ev.get("watchlist_hits") or []}
    subject_holder = ev.get("subject", {}).get("holder_id") or ev.get("subject", {}).get("id")
    net = _net(height)
    for m in members:
        color = COLORS["watchlisted"] if m in listed else COLORS["individual"]
        title = f"{m}\n{labels.get(m, '')}\nonboarded {netb.get('onboarded', {}).get(m, '?')}" + (f"\nON {listed[m].upper()} LIST" if m in listed else "")
        net.add_node(m, label=m, title=title, color=color, shape="dot", size=26 if m == subject_holder else 18,
                     borderWidth=4 if m == subject_holder else 1)
    for link in netb.get("shared_links") or []:
        lt = link["type"]
        nid = f"{lt}:{link.get('value') or ','.join(link.get('address_ids', [])[:1])}"
        lab = link.get("value", "")[:15] if lt != "address" else f"address ({link.get('country') or ''})"
        net.add_node(nid, label=f"{LINK_LABEL.get(lt, lt)}\n{lab}", title=f"{lt} shared by {link['n_identities']} identities\n{link.get('value', ', '.join(link.get('address_ids', [])[:4]))}",
                     color=COLORS.get(lt, COLORS["other_id"]), shape="diamond" if lt == "device_fingerprint" else "triangle", size=14)
        for m in link["members"]:
            if m in members:
                net.add_edge(nid, m, color=COLORS.get(lt, COLORS["other_id"]), width=2)
    accts = ev.get("accounts") or []
    if len(accts) <= 60:
        for a in accts:
            holder = a.get("individual_id") or a.get("entity_id")
            if holder in members:
                net.add_node(a["account_id"], label=a["account_id"], title=f"{a['account_id']} {a.get('account_type')} risk={a.get('risk_rating')}",
                             color=COLORS["account"], shape="square", size=8, font={"size": 9})
                net.add_edge(holder, a["account_id"], color="#cbd5e1", width=1)
    return net.generate_html(notebook=False)


def ownership_network(ev: dict, labels: dict[str, str] | None = None, height: int = 480) -> str | None:
    own = ev.get("ownership") or {}
    subj = (ev.get("entity") or {}).get("entity_id") or ev.get("subject", {}).get("entity_id") or ev.get("subject", {}).get("id")
    if not subj:
        return None
    labels = labels or {}
    listed = {w["subject_id"] for w in ev.get("watchlist_hits") or [] if w.get("list_type") == "Sanctions-like"}
    net = _net(height)

    def add(e: str, size: int = 16) -> None:
        net.add_node(e, label=e, title=f"{e}\n{labels.get(e, '')}" + ("\nSANCTIONS-LIKE LIST" if e in listed else ""),
                     color=COLORS["sanctioned"] if e in listed else (COLORS["subject"] if e == subj else COLORS["entity"]), shape="dot", size=size)

    add(subj, 24)
    for hop in own.get("chain") or []:
        add(hop["parent_entity_id"]); add(hop["child_entity_id"])
        net.add_edge(hop["parent_entity_id"], hop["child_entity_id"], label=f"{hop['ownership_pct']:.1f}%", color="#dc2626", width=3, arrows="to")
    for p in own.get("direct_owners") or []:
        add(p["parent_entity_id"], 12)
        net.add_edge(p["parent_entity_id"], subj, label=f"{p['ownership_pct']:.1f}% {p['link_type']}", color="#94a3b8", arrows="to")
    for c in own.get("direct_holdings") or []:
        add(c["child_entity_id"], 12)
        net.add_edge(subj, c["child_entity_id"], label=f"{c['ownership_pct']:.1f}% {c['link_type']}", color="#94a3b8", arrows="to")
    return net.generate_html(notebook=False)
