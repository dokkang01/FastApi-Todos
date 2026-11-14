import json
import threading
import logging                                   # ← 추가
import sys                                       # ← 추가
import time                                      # ← 추가
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator  # ← 추가
from pydantic import BaseModel, Field, model_validator


BASE_DIR = Path(__file__).resolve().parent       # main.py 가 있는 폴더
TODO_FILE = BASE_DIR / "todo.json"
INDEX_FILE = BASE_DIR / "templates" / "index.html"
TODO_LOCK = threading.Lock()                     # 동시 요청이 todo.json 을 함께 읽고 쓰지 못하게 막는다

if not TODO_FILE.exists():                       # 없으면 빈 목록으로 만들어 둔다
    TODO_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="To-Do List API")

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# ← 추가: 액세스 로그를 표준 출력(stdout)으로 기록
#   Docker가 stdout을 컨테이너 로그로 저장하고, Alloy가 그 로그를 읽어 Loki로 전송
custom_logger = logging.getLogger("custom.access")
custom_logger.setLevel(logging.INFO)
custom_logger.addHandler(logging.StreamHandler(sys.stdout))
custom_logger.propagate = False                  # 상위 로거로 넘겨 두 번 찍히는 것을 방지

# ← 추가: uvicorn 기본 액세스 로그 끄기 (아래 미들웨어가 대신 기록)
#   켜 두면 요청 1번에 로그가 2줄씩 남아 대시보드 카운트가 2배가 됨
logging.getLogger("uvicorn.access").disabled = True


@app.middleware("http")                          # ← 추가: 모든 요청을 한 줄씩 기록
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    client = request.client.host if request.client else "-"
    # 형식: IP - "METHOD PATH HTTP/1.1" 상태코드 응답시간 → 7번 LogQL 쿼리가 이 형식으로 파싱
    custom_logger.info(
        f'{client} - "{request.method} {request.url.path} HTTP/1.1" '
        f'{response.status_code} {duration:.3f}s'
    )
    return response


class TodoIn(BaseModel):                         # 클라이언트가 보내는 데이터 (id 없음)
    title: str = Field(min_length=1, max_length=100)
    description: str = ""
    completed: bool = False
    due_date: date | None = None                 # 마감일 (없어도 된다)
    priority: Literal["high", "medium", "low"] = "medium"   # 우선순위 (기존 데이터는 보통으로 읽힌다)
    stage: Literal["todo", "doing", "done"] = "todo"        # 칸반 단계: 할 일 → 진행 중 → 완료

    @model_validator(mode="after")
    def sync_stage_and_completed(self):
        # stage 와 completed 가 항상 같은 뜻이 되게 맞춘다 (done ⇔ completed=True)
        # stage 를 안 보낸 요청·기존 데이터는 completed 로 정하고, 보냈으면 stage 가 우선한다
        if "stage" not in self.model_fields_set:
            self.stage = "done" if self.completed else "todo"
        self.completed = self.stage == "done"
        return self


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}   # 우선순위 정렬 순서


class TodoItem(TodoIn):                          # 서버가 돌려주는 데이터 (id 있음)
    id: int


def load_todos() -> list[TodoItem]:
    raw = TODO_FILE.read_text(encoding="utf-8") if TODO_FILE.exists() else "[]"
    return [TodoItem(**t) for t in json.loads(raw)]


def save_todos(todos: list[TodoItem]) -> None:
    data = json.dumps([t.model_dump(mode="json") for t in todos], indent=2, ensure_ascii=False)
    TODO_FILE.write_text(data, encoding="utf-8")


def find_index(todos: list[TodoItem], todo_id: int) -> int:
    for i, todo in enumerate(todos):
        if todo.id == todo_id:
            return i
    raise HTTPException(404, "To-Do item not found")


@app.get("/todos")                               # 목록 조회 — ?sort=due_date 마감일 빠른 순, ?sort=priority 우선순위 높은 순
def get_todos(
    sort: Literal["id", "due_date", "priority"] = "id",
    status: Literal["all", "active", "completed"] = "all",   # active = 진행 중, completed = 완료
    q: str = Query("", max_length=100),                       # 제목·설명 검색어 (대소문자 무시)
) -> list[TodoItem]:
    with TODO_LOCK:
        todos = load_todos()
    if status != "all":
        todos = [t for t in todos if t.completed == (status == "completed")]
    if keyword := q.strip().casefold():
        todos = [t for t in todos if keyword in t.title.casefold() or keyword in t.description.casefold()]
    if sort == "due_date":                       # 마감일 없는 항목은 맨 뒤, 같은 날짜는 등록순
        todos.sort(key=lambda t: (t.due_date is None, t.due_date or date.max, t.id))
    elif sort == "priority":                     # 높음 → 보통 → 낮음, 같은 우선순위는 등록순
        todos.sort(key=lambda t: (PRIORITY_RANK[t.priority], t.id))
    return todos


@app.post("/todos", status_code=201)             # 추가 — id 는 서버가 매긴다
def create_todo(payload: TodoIn) -> TodoItem:
    with TODO_LOCK:                              # 읽기~저장 사이에 끼어들면 id 중복·파일 깨짐이 생긴다
        todos = load_todos()
        new_id = max((t.id for t in todos), default=0) + 1
        todo = TodoItem(id=new_id, **payload.model_dump())
        save_todos(todos + [todo])
    return todo


@app.put("/todos/{todo_id}", responses={404: {"description": "해당 id의 To-Do 항목이 없음"}})  # 수정
def update_todo(todo_id: int, payload: TodoIn) -> TodoItem:
    todo = TodoItem(id=todo_id, **payload.model_dump())
    with TODO_LOCK:
        todos = load_todos()
        todos[find_index(todos, todo_id)] = todo
        save_todos(todos)
    return todo


@app.delete("/todos/{todo_id}", status_code=204,
            responses={404: {"description": "해당 id의 To-Do 항목이 없음"}})  # 삭제
def delete_todo(todo_id: int) -> None:
    with TODO_LOCK:
        todos = load_todos()
        del todos[find_index(todos, todo_id)]
        save_todos(todos)


@app.get("/", include_in_schema=False)           # 화면 서빙
def read_root() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html")