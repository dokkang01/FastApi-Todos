// To-Do API 부하 테스트 — 각 VU가 생성 → 조회 → 수정 → 삭제를 반복한다
// 실행: k6 run k6/load-test.js
//       k6 run -e BASE_URL=http://localhost:8012 k6/load-test.js   (대상 변경)
import http from "k6/http";
import { check, group, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://100.82.86.31:8012";
const MAX_VUS = Number(__ENV.MAX_VUS || 50);    // 최대 VU 수 (-e MAX_VUS=20 처럼 바꿀 수 있다)
const JSON_HEADERS = { headers: { "Content-Type": "application/json" } };

export const options = {
  stages: [                                      // MAX_VUS까지 단계적으로 올린다 (총 5분)
    { duration: "1m", target: Math.ceil(MAX_VUS / 2) },
    { duration: "1m", target: MAX_VUS },
    { duration: "2m30s", target: MAX_VUS },      // 최대 부하 유지
    { duration: "30s", target: 0 },              // 정리
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],              // 에러율 1% 미만
    http_req_duration: ["p(95)<500"],            // 95% 요청이 500ms 안에 응답
    checks: ["rate>0.99"],
  },
};

export default function () {
  let todoId;

  group("생성", () => {
    const payload = JSON.stringify({
      title: `k6-${__VU}-${__ITER}`,
      description: "k6 부하 테스트용 항목",
      due_date: "2026-12-31",
    });
    const res = http.post(`${BASE_URL}/todos`, payload, JSON_HEADERS);
    check(res, { "POST 201": (r) => r.status === 201 });
    if (res.status === 201) todoId = res.json("id");
    else console.warn(`POST 실패: status=${res.status} body=${String(res.body).slice(0, 200)}`);
  });

  group("조회", () => {
    const res = http.get(`${BASE_URL}/todos?sort=due_date`);
    check(res, { "GET 200": (r) => r.status === 200 });
  });

  if (todoId === undefined) {                    // 생성 실패 시 수정·삭제는 건너뛴다
    sleep(1);                                    // 실패해도 쉬어야 요청이 폭주하지 않는다
    return;
  }

  group("수정", () => {
    const payload = JSON.stringify({
      title: `k6-${__VU}-${__ITER}-done`,
      completed: true,
    });
    const res = http.put(`${BASE_URL}/todos/${todoId}`, payload, {
      ...JSON_HEADERS,
      tags: { name: "PUT /todos/{id}" },         // id별로 메트릭이 쪼개지지 않게 묶는다
    });
    check(res, { "PUT 200": (r) => r.status === 200 });
  });

  group("삭제", () => {
    const res = http.del(`${BASE_URL}/todos/${todoId}`, null, {
      tags: { name: "DELETE /todos/{id}" },
    });
    check(res, { "DELETE 204": (r) => r.status === 204 });
  });

  sleep(1);                                      // 실제 사용자처럼 요청 사이에 쉬는 시간
}
