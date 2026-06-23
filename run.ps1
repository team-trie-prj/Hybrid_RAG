# 대전 하이브리드 RAG 프로토타입 실행 헬퍼 (Windows)
# anaconda의 sqlite3 DLL 경로(Library\bin)를 PATH에 추가해야 import 오류가 안 남.
param([string]$cmd = "demo")

$conda = "C:\Users\user\anaconda3"
$env:PATH = "$conda;$conda\Library\bin;$conda\Scripts;" + $env:PATH
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location "$PSScriptRoot\src"

switch ($cmd) {
    "etl"    { python etl.py; python ingest.py "../data/normalized.jsonl" }   # 레지스트리 ETL→적재
    "loadapi"{ python load_datago.py @($args); python ingest.py "../data/normalized.jsonl" }  # 실API 수집→적재
    "ingest" { python ingest.py "../data/normalized.jsonl" }
    "demo"   { python demo.py }
    "ask"    { python agent.py @($args) }
    "report" { python report.py @($args) }                                    # .docx 보고서 생성
    "serve"  { python server.py 8000 }                                        # UI 서버 → localhost:8000
    default  { python etl.py; python ingest.py "../data/normalized.jsonl"; python demo.py }
}
