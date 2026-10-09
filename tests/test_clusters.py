"""Identity clustering: shared identifiers of any type join people into one connected component."""
import pandas as pd

from core import data, precompute

LINKS = pd.DataFrame(
    [
        ("device_fingerprint", "fp_aaa", "I1", 2), ("device_fingerprint", "fp_aaa", "I2", 2),
        ("phone", "h1", "I2", 2), ("phone", "h1", "I3", 2),
        ("address", "1 main st | 1000", "I3", 2), ("address", "1 main st | 1000", "I4", 2),
        ("email", "h9", "I8", 2), ("email", "h9", "I9", 2),
    ],
    columns=["link_type", "link_value", "individual_id", "n_members"],
)


def test_components_chain_through_different_link_types(monkeypatch):
    monkeypatch.setattr(data, "q", lambda sql, params=None: LINKS.copy())
    links, clusters = precompute.build_identity_graph()
    c = clusters.set_index("individual_id")
    assert len({c.loc[i, "cluster_id"] for i in ("I1", "I2", "I3", "I4")}) == 1
    assert c.loc["I1", "cluster_size"] == 4
    assert c.loc["I8", "cluster_id"] != c.loc["I1", "cluster_id"] and c.loc["I8", "cluster_size"] == 2
    assert set(c.loc["I1", "cluster_link_types"].split(",")) == {"device_fingerprint", "phone", "address"}
    assert c.loc["I1", "cluster_id"] == "CL00001", "largest cluster gets the first ID"
