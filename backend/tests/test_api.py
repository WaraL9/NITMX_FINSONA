def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seeded_case(client):
    cases = client.get("/api/cases").json()
    assert len(cases) == 1
    case = client.get(f"/api/cases/{cases[0]['id']}").json()
    assert case["company_name"] == "บริษัท กิตติ อินทีเรีย ดีไซน์ จำกัด"
    assert case["requested_amount"] == "5000000.00"  # money is a string on the wire
    assert case["annual_rate"] == "0.07"
    assert {a["owner_type"] for a in case["accounts"]} == {"company", "director"}
    assert len(case["accounts"]) == 4


def test_create_case_validates(client):
    bad = client.post("/api/cases", json={"company_name": "", "industry": "x", "business_age_years": 1,
                                          "requested_amount": "-1", "purpose": "x", "tenor_months": 12,
                                          "annual_rate": "0.07"})
    assert bad.status_code == 422

    ok = client.post("/api/cases", json={"company_name": "ร้านทดสอบ", "industry": "ค้าปลีก",
                                         "business_age_years": 2, "requested_amount": "1000000",
                                         "purpose": "ทดสอบ", "tenor_months": 24, "annual_rate": "0.065"})
    assert ok.status_code == 201
    assert ok.json()["requested_amount"] == "1000000.00"


def test_missing_case_404(client):
    assert client.get("/api/cases/9999").status_code == 404
