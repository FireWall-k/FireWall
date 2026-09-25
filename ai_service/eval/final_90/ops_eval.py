"""최종 평가셋(신규 90문항)을 실제 서비스 경로로 돌려 결과를 저장한다.

사업주가 업종을 넣어 직무를 만드는 경로(POST /api/tasks) 그대로 실행하고, 단계마다 채택된 그림과
검토 화면이 보여 줄 후보(symbol-candidates)를 함께 기록한다. 채점은 사람이 ops_grading.md 기준으로 한다.

사용: 백엔드·AI 서비스를 띄운 뒤(운영 설정을 재려면 OPENAI_API_KEY와 함께)
    python ops_eval.py 1            # → ops_run1.json
    JOBCARD_API=http://localhost:8000 JOBCARD_LOGIN=demo JOBCARD_PASSWORD=demo1234 python ops_eval.py 2
"""
import json
import os
import sys
import time

import httpx

from final_set import SET

B = os.getenv("JOBCARD_API", "http://localhost:8000")
run = sys.argv[1] if len(sys.argv) > 1 else "1"

with httpx.Client(timeout=120) as http:
    t = http.post(f"{B}/api/auth/login", json={
        "login_id": os.getenv("JOBCARD_LOGIN", "demo"),
        "password": os.getenv("JOBCARD_PASSWORD", "demo1234"),
    }).json()["token"]
    H = {"Authorization": f"Bearer {t}"}
    rows, t0 = [], time.time()
    for biz, sents in SET.items():
        for s in sents:
            st = time.time()
            r = http.post(f"{B}/api/tasks", headers=H, json={"raw_input": s, "business_type": biz}).json()
            entry = dict(biz=biz, sentence=s, latency_sec=round(time.time() - st, 2), steps=[])
            for x in r["steps"]:
                ok = x["symbol_url"] and not x["needs_fallback"]
                c = http.get(f"{B}/api/tasks/{r['id']}/steps/{x['id']}/symbol-candidates", headers=H)
                entry["steps"].append(dict(
                    sentence=x["sentence"], action_type=x["action_type"],
                    chosen=(x["symbol_url"] or "").split("/")[-1].replace(".webp", "") if ok else None,
                    source=x["symbol_source"], cands=c.json() if c.status_code == 200 else {}))
            rows.append(entry)
            print(len(rows), s, "->", [st_["chosen"] for st_ in entry["steps"]], flush=True)

out = dict(run=run, started=time.strftime("%Y-%m-%d %H:%M:%S"), total_sec=round(time.time() - t0, 1), rows=rows)
# 인코딩을 명시한다. 예전 키트는 지정하지 않아 Windows에서 cp949로 저장됐다.
with open(f"ops_run{run}.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("saved", f"ops_run{run}.json")
