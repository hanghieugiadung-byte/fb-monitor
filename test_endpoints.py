import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app
from core.db import init_db, get_db_session, GroupItem, TopicItem, MonitorSchedule

def run_tests():
    init_db()
    client = TestClient(app)

    print("--- 1. Testing GET /api/state ---")
    res = client.get("/api/state")
    assert res.status_code == 200, f"GET /api/state failed: {res.status_code} {res.text}"
    data = res.json()
    assert "topics" in data, "topics missing in /api/state"
    assert "schedules" in data, "schedules missing in /api/state"
    assert "groups" in data, "groups missing in /api/state"
    print(f"✓ /api/state OK. Topics: {len(data['topics'])}, Schedules: {len(data['schedules'])}, Groups: {len(data['groups'])}")

    print("--- 2. Testing Topic CRUD ---")
    res = client.post("/api/topics", json={"name": "Test Chu De 999", "color": "emerald"})
    assert res.status_code == 200, f"Create topic failed: {res.text}"
    topic_data = res.json()
    assert topic_data["name"] == "Test Chu De 999"
    topic_id = topic_data["id"]
    print(f"✓ Created topic ID {topic_id}")

    # Duplicate topic should be handled
    res_dup = client.post("/api/topics", json={"name": "Test Chu De 999", "color": "emerald"})
    assert res_dup.status_code == 200

    print("--- 3. Testing Group Operations ---")
    # Add a group
    res_g = client.post("/api/groups", json={
        "name": "Nhom Test Perm",
        "fb_url": "https://www.facebook.com/groups/123456789999",
        "topic_name": "Test Chu De 999"
    })
    assert res_g.status_code == 200, f"Add group failed: {res_g.text}"
    group_id = res_g.json()["id"]
    print(f"✓ Created group ID {group_id}")

    # Update group topic
    res_t = client.post(f"/api/groups/{group_id}/topic", json={"topic_name": "Kinh Doanh"})
    assert res_t.status_code == 200, f"Update topic failed: {res_t.text}"
    assert res_t.json()["topic_name"] == "Kinh Doanh"
    print("✓ Update group topic OK")

    # Toggle group joined
    res_j = client.post(f"/api/groups/{group_id}/joined")
    assert res_j.status_code == 200, f"Toggle joined failed: {res_j.text}"
    assert res_j.json()["is_joined"] == True
    res_j2 = client.post(f"/api/groups/{group_id}/joined")
    assert res_j2.json()["is_joined"] == False
    print("✓ Toggle group joined OK")

    print("--- 4. Testing Schedules CRUD ---")
    res_s = client.post("/api/schedules", json={
        "name": "Ca sang 08h-12h",
        "account_id": None,
        "group_ids": [group_id],
        "keyword_ids": [],
        "interval_minutes": 15,
        "start_time": "08:00",
        "end_time": "12:00"
    })
    assert res_s.status_code == 200, f"Create schedule failed: {res_s.text}"
    sched_id = res_s.json()["id"]
    print(f"✓ Created schedule ID {sched_id}")

    # Toggle schedule
    res_st = client.post(f"/api/schedules/{sched_id}/toggle")
    assert res_st.status_code == 200
    assert res_st.json()["is_active"] == False
    res_st2 = client.post(f"/api/schedules/{sched_id}/toggle")
    assert res_st2.json()["is_active"] == True
    print("✓ Toggle schedule OK")

    # Run schedule now
    res_sr = client.post(f"/api/schedules/{sched_id}/run-now")
    assert res_sr.status_code == 200, f"Run schedule now failed: {res_sr.text}"
    print(f"✓ Run schedule now OK: {res_sr.json()}")

    # Delete schedule
    res_sd = client.delete(f"/api/schedules/{sched_id}")
    assert res_sd.status_code == 200
    print("✓ Delete schedule OK")

    # Delete topic
    res_td = client.delete(f"/api/topics/{topic_id}")
    assert res_td.status_code == 200
    print("✓ Delete topic OK")

    # Clean up group
    client.delete(f"/api/groups/{group_id}")

    # Clear posts
    res_cp = client.post("/api/posts/clear")
    assert res_cp.status_code == 200
    print("✓ Clear posts OK")

    print("\n✅ ALL ENDPOINT INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
