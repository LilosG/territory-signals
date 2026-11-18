"""Rebuild the small fixture files in tests/fixtures/ from recon/samples/.

Run once from the repo root:  .venv/bin/python tests/fixtures/build_fixtures.py
Names and phone numbers are synthetic: the real sample rows are used only for
their structure, coordinates, ids, types and dates.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "recon" / "samples"
OUT = Path(__file__).resolve().parent


def stro():
    df = pd.read_csv(SAMPLES / "stro_licenses_92037_92109_sample.csv", dtype=str).head(10)
    df = df.copy()
    df["host_contact_name"] = [f"Test Host {i}" for i in range(len(df))]
    df["local_contact_contact_name"] = [f"Test Contact {i}" for i in range(len(df))]
    df["local_contact_phone"] = [f"619-555-01{i:02d}" for i in range(len(df))]
    # one license outside the territory (Los Angeles coordinates)
    out = df.iloc[0].copy()
    out["license_id"], out["longitude"], out["latitude"] = "STR-OUTSIDE", "-118.40", "34.00"
    out["community_planning_area"] = "OTHER"
    df = pd.concat([df, out.to_frame().T], ignore_index=True)
    df.to_csv(OUT / "stro_licenses_fixture.csv", index=False)


def permits():
    df = pd.read_csv(SAMPLES / "dev_permits_issued_92037_92109_sample.csv", dtype=str)
    df = df.drop_duplicates("APPROVAL_ID").head(14).copy()
    df["APPROVAL_PERMIT_HOLDER"] = [f"Test Holder {i}" for i in range(len(df))]
    df["APPROVAL_ADU_TOTAL"] = df.get("APPROVAL_ADU_TOTAL", "0")
    df = df.reset_index(drop=True)
    # row 0: blank APN, coordinates inside its parcel -> spatial match
    df.loc[0, "GIS_APN"] = None
    # row 1: blank APN, no coordinates, address equals a parcel -> address match
    df.loc[1, ["GIS_APN", "GIS_LATITUDE", "GIS_LONGITUDE"]] = [None, None, None]
    # row 2: APN not in the territory, coordinates far away -> excluded
    df.loc[2, ["GIS_APN", "GIS_LATITUDE", "GIS_LONGITUDE"]] = ["9999999999", "34.00", "-118.40"]
    # row 3: issued, expiry passed, never closed -> permit_stalled
    df.loc[3, ["APPROVAL_STATUS", "APPROVAL_ISSUE_DATE", "APPROVAL_EXPIRE_DATE", "APPROVAL_CLOSE_DATE"]] = [
        "Issued", "2024-01-10", "2025-01-10", None]
    # row 4: expiry passed but closed -> NOT stalled
    df.loc[4, ["APPROVAL_STATUS", "APPROVAL_ISSUE_DATE", "APPROVAL_EXPIRE_DATE", "APPROVAL_CLOSE_DATE"]] = [
        "Closed", "2024-01-10", "2025-01-10", "2024-06-01"]
    # row 5: a type that is not in the map -> signal_group other
    df.loc[5, "APPROVAL_TYPE"] = "Brand New Approval Type"
    df.to_csv(OUT / "approvals_issued_fixture.csv", index=False)


def _pdf(path, items):
    """Minimal one-page text PDF. items = [(x, y, text)] in points."""
    stream = "BT /F1 6 Tf\n" + "".join(
        f"1 0 0 1 {x} {y} Tm ({t.replace(chr(92), chr(92)*2).replace('(', chr(92)+'(').replace(')', chr(92)+')')}) Tj\n"
        for x, y, t in items) + "ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    Path(path).write_bytes(out.encode("latin-1"))


def tax():
    df = pd.read_csv(SAMPLES / "sdttc_impending_power_to_sell_92037_92109.csv", dtype=str).head(6)
    items = [(36, 760, "NOTICE OF IMPENDING POWER TO SELL TAX-DEFAULTED PROPERTY"),
             (36, 748, "The parcels listed herein will become subject to the tax collector power"),
             (36, 738, "to sell on July 1, 2026, at 12:01 a.m., by operation of law."),
             (36, 700, "Property tax-defaulted on June 30, 2021 for fiscal year 2020-2021:")]
    for i, r in enumerate(df.itertuples()):
        rest = r.rest_of_line_raw
        amount = rest[rest.rfind("$"):]
        before = rest[:rest.rfind("$")].strip()
        words = before.split()
        # keep the street part (from the first zero-padded number on) and drop the real names
        k = next((j for j, w in enumerate(words) if w[:5].isdigit() and w[0] == "0"), len(words))
        addr = " ".join(words[k:])
        name = ["TEST OWNER %d" % i, "TEST OWNER %d EST OF" % i, "TEST FAMILY TRUST"][i % 3]
        x = 36 if i % 2 == 0 else 330        # two columns, like the real notice
        y = 680 - (i // 2) * 14
        items.append((x, y, f"{r.apn_fmt} {name} {addr} {amount}"))
    _pdf(OUT / "tax_default_fixture.pdf", items)


if __name__ == "__main__":
    stro()
    permits()
    tax()
    print("fixtures written to", OUT)
