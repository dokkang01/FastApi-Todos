import pytest
from fastapi.testclient import TestClient

import main
from main import app, save_todos, load_todos, TodoItem

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_and_teardown(tmp_path, monkeypatch):
    # 실제 todo.json 대신 테스트마다 새 임시 파일 사용 (본인 데이터 보호 + 테스트 간 격리)
    # TODO_FILE 은 본인 main.py의 파일 경로 변수명에 맞게 수정 (Path 객체 그대로 넘김, str()로 감싸지 않음)
    monkeypatch.setattr(main, "TODO_FILE", tmp_path / "todo.json")
    save_todos([])  # 테스트 전 초기화
    return
    # 테스트 후 정리: tmp_path 와 monkeypatch 가 자동으로 원상 복구

def test_get_todos_empty():
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []

def test_get_todos_with_items():
    todo = TodoItem(id=1, title="Test", description="Test description", completed=False)
    save_todos([todo])  # save_todos 는 TodoItem 객체 리스트를 받음
    response = client.get("/todos")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test"

def test_create_todo():
    todo = {"title": "Test", "description": "Test description", "completed": False}  # id 는 보내지 않음
    response = client.post("/todos", json=todo)
    assert response.status_code == 201           # 생성 성공 = 201 Created
    assert response.json()["title"] == "Test"
    assert response.json()["id"] == 1            # id 는 서버가 부여
    assert len(load_todos()) == 1                # 파일에도 저장됐는지 확인

def test_create_todo_invalid():
    todo = {"description": "Test description"}   # 필수 필드 title 누락
    response = client.post("/todos", json=todo)
    assert response.status_code == 422

def test_update_todo():
    todo = TodoItem(id=1, title="Test", description="Test description", completed=False)
    save_todos([todo])
    updated_todo = {"title": "Updated", "description": "Updated description", "completed": True}
    response = client.put("/todos/1", json=updated_todo)
    assert response.status_code == 200
    assert response.json()["title"] == "Updated"

def test_update_todo_not_found():
    updated_todo = {"title": "Updated", "description": "Updated description", "completed": True}
    response = client.put("/todos/1", json=updated_todo)
    assert response.status_code == 404

def test_delete_todo():
    todo = TodoItem(id=1, title="Test", description="Test description", completed=False)
    save_todos([todo])
    response = client.delete("/todos/1")
    assert response.status_code == 204           # 삭제 성공 = 204 No Content (응답 본문 없음)
    assert load_todos() == []

def test_delete_todo_not_found():
    response = client.delete("/todos/1")
    assert response.status_code == 404

def test_get_todos_sorted_by_due_date():
    save_todos([
        TodoItem(id=1, title="마감 없음"),
        TodoItem(id=2, title="늦은 마감", due_date="2026-12-01"),
        TodoItem(id=3, title="빠른 마감", due_date="2026-10-01"),
        TodoItem(id=4, title="같은 날 나중 등록", due_date="2026-10-01"),
    ])
    response = client.get("/todos?sort=due_date")
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [3, 4, 2, 1]  # 빠른 순, 같은 날은 등록순, 마감 없음은 맨 뒤

def test_get_todos_default_order_is_id():
    save_todos([TodoItem(id=1, title="A", due_date="2026-12-01"), TodoItem(id=2, title="B", due_date="2026-10-01")])
    response = client.get("/todos")
    assert [t["id"] for t in response.json()] == [1, 2]       # sort 없으면 기존처럼 등록순

def test_get_todos_invalid_sort():
    response = client.get("/todos?sort=title")
    assert response.status_code == 422

def test_get_todos_filter_by_status():
    save_todos([TodoItem(id=1, title="A"), TodoItem(id=2, title="B", completed=True), TodoItem(id=3, title="C")])
    assert [t["id"] for t in client.get("/todos?status=active").json()] == [1, 3]
    assert [t["id"] for t in client.get("/todos?status=completed").json()] == [2]
    assert [t["id"] for t in client.get("/todos?status=all").json()] == [1, 2, 3]

def test_get_todos_search_title_and_description():
    save_todos([
        TodoItem(id=1, title="DevOps 과제", description=""),
        TodoItem(id=2, title="장보기", description="devops 스터디 간식"),
        TodoItem(id=3, title="운동", description="헬스장"),
    ])
    response = client.get("/todos", params={"q": "  DEVOPS "})
    assert [t["id"] for t in response.json()] == [1, 2]       # 제목·설명 모두, 대소문자·앞뒤 공백 무시

def test_get_todos_blank_search_returns_all():
    save_todos([TodoItem(id=1, title="A"), TodoItem(id=2, title="B")])
    assert len(client.get("/todos?q=").json()) == 2

def test_get_todos_filter_search_and_sort_combined():
    save_todos([
        TodoItem(id=1, title="보고서 초안", due_date="2026-12-01"),
        TodoItem(id=2, title="보고서 제출", due_date="2026-11-10"),
        TodoItem(id=3, title="보고서 검토", completed=True, due_date="2026-11-05"),
        TodoItem(id=4, title="회의", due_date="2026-11-01"),
    ])
    response = client.get("/todos?status=active&q=보고서&sort=due_date")
    assert [t["id"] for t in response.json()] == [2, 1]

def test_get_todos_invalid_status():
    response = client.get("/todos?status=done")
    assert response.status_code == 422

def test_get_todos_search_too_long():
    response = client.get("/todos", params={"q": "a" * 101})
    assert response.status_code == 422

def test_create_todo_default_priority():
    response = client.post("/todos", json={"title": "Test"})
    assert response.status_code == 201
    assert response.json()["priority"] == "medium"         # 보내지 않으면 보통

def test_create_todo_with_priority():
    response = client.post("/todos", json={"title": "Test", "priority": "high"})
    assert response.json()["priority"] == "high"
    assert load_todos()[0].priority == "high"

def test_create_todo_invalid_priority():
    response = client.post("/todos", json={"title": "Test", "priority": "urgent"})
    assert response.status_code == 422

def test_update_todo_priority():
    save_todos([TodoItem(id=1, title="Test")])
    response = client.put("/todos/1", json={"title": "Test", "priority": "low"})
    assert response.json()["priority"] == "low"

def test_get_todos_sorted_by_priority():
    save_todos([
        TodoItem(id=1, title="낮음", priority="low"),
        TodoItem(id=2, title="보통"),
        TodoItem(id=3, title="높음", priority="high"),
        TodoItem(id=4, title="높음 나중 등록", priority="high"),
    ])
    response = client.get("/todos?sort=priority")
    assert [t["id"] for t in response.json()] == [3, 4, 2, 1]  # 높음 → 보통 → 낮음, 같은 우선순위는 등록순

def test_get_todos_priority_sort_with_filter():
    save_todos([
        TodoItem(id=1, title="A", priority="low"),
        TodoItem(id=2, title="B", priority="high", completed=True),
        TodoItem(id=3, title="C", priority="high"),
    ])
    response = client.get("/todos?status=active&sort=priority")
    assert [t["id"] for t in response.json()] == [3, 1]

def test_create_todo_default_stage():
    response = client.post("/todos", json={"title": "Test"})
    assert response.json()["stage"] == "todo"              # 새 할 일은 '할 일' 칸에서 시작
    assert response.json()["completed"] is False

def test_create_todo_with_stage():
    response = client.post("/todos", json={"title": "Test", "stage": "doing"})
    assert response.status_code == 201
    assert response.json()["stage"] == "doing"
    assert load_todos()[0].stage == "doing"

def test_create_todo_invalid_stage():
    response = client.post("/todos", json={"title": "Test", "stage": "blocked"})
    assert response.status_code == 422

def test_move_todo_between_stages():
    save_todos([TodoItem(id=1, title="Test")])
    doing = client.put("/todos/1", json={"title": "Test", "stage": "doing"}).json()
    assert (doing["stage"], doing["completed"]) == ("doing", False)
    done = client.put("/todos/1", json={"title": "Test", "stage": "done"}).json()
    assert (done["stage"], done["completed"]) == ("done", True)  # 완료 칸으로 옮기면 완료 처리

def test_stage_wins_over_completed():
    response = client.post("/todos", json={"title": "Test", "stage": "doing", "completed": True})
    assert (response.json()["stage"], response.json()["completed"]) == ("doing", False)

def test_completed_only_request_sets_stage():
    save_todos([TodoItem(id=1, title="Test", stage="doing")])
    response = client.put("/todos/1", json={"title": "Test", "completed": True})  # stage 를 모르는 기존 클라이언트
    assert (response.json()["stage"], response.json()["completed"]) == ("done", True)

def test_legacy_data_without_stage():
    main.TODO_FILE.write_text(
        '[{"id": 1, "title": "A", "completed": true}, {"id": 2, "title": "B", "completed": false}]',
        encoding="utf-8",
    )
    assert [t["stage"] for t in client.get("/todos").json()] == ["done", "todo"]  # 기존 todo.json 도 그대로 읽힌다

def test_status_filter_with_stages():
    save_todos([TodoItem(id=1, title="A"), TodoItem(id=2, title="B", stage="doing"), TodoItem(id=3, title="C", stage="done")])
    assert [t["id"] for t in client.get("/todos?status=active").json()] == [1, 2]  # 미완료 = 할 일 + 진행 중
    assert [t["id"] for t in client.get("/todos?status=completed").json()] == [3]
