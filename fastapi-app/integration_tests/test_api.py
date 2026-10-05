import os
import time

import pytest
import requests

# 테스트할 서버 주소 (Jenkins 에서 환경변수 BASE_URL 로 넘겨준다)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8012")


@pytest.fixture(scope="session", autouse=True)
def wait_for_server():
    # 방금 docker run 한 컨테이너가 뜰 때까지 최대 30초 기다린다
    for _ in range(30):
        try:
            if requests.get(f"{BASE_URL}/todos", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    pytest.fail(f"서버가 응답하지 않음: {BASE_URL}")


def test_crud_flow():
    # 추가 → 201
    res = requests.post(f"{BASE_URL}/todos", json={"title": "통합테스트", "description": "jenkins"})
    assert res.status_code == 201
    todo_id = res.json()["id"]

    # 조회 → 200, 방금 추가한 항목이 있어야 함
    res = requests.get(f"{BASE_URL}/todos")
    assert res.status_code == 200
    assert any(t["id"] == todo_id for t in res.json())

    # 수정 → 200
    res = requests.put(f"{BASE_URL}/todos/{todo_id}", json={"title": "수정됨", "completed": True})
    assert res.status_code == 200
    assert res.json()["title"] == "수정됨"

    # 삭제 → 204 (테스트 데이터가 서버에 남지 않게 정리도 겸함)
    res = requests.delete(f"{BASE_URL}/todos/{todo_id}")
    assert res.status_code == 204


def test_create_without_title_returns_422():
    res = requests.post(f"{BASE_URL}/todos", json={"description": "제목 없음"})
    assert res.status_code == 422


def test_delete_missing_id_returns_404():
    res = requests.delete(f"{BASE_URL}/todos/999999")
    assert res.status_code == 404
