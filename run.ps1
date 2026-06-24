# 대전 하이브리드 RAG 프로토타입 실행 헬퍼 (Windows)
# anaconda의 sqlite3 DLL 경로(Library\bin)를 PATH에 추가해야 import 오류가 안 남.
param([string]$cmd = "demo")

$conda = "C:\Users\user\anaconda3"
$env:PATH = "$conda;$conda\Library\bin;$conda\Scripts;" + $env:PATH
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# .env 자동 로드 (KEY=VALUE 형식). 키 파일은 .gitignore로 커밋 제외.
# 세션 한정($env:)·영구등록 후 미재시작 문제를 피하기 위한 안정적 경로.
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim().Trim('"'), "Process")
        }
    }
}

Set-Location "$PSScriptRoot\src"

switch ($cmd) {
    "etl"    { python etl.py; python ingest.py "../data/normalized.jsonl" }   # 레지스트리 ETL→적재
    "loadapi"{ python load_datago.py @($args); python ingest.py "../data/normalized.jsonl" }  # 실API 수집→적재
    "ingest" { python ingest.py "../data/normalized.jsonl" }
    "demo"   { python demo.py }
    "ask"    { python agent.py @($args) }
    "report" { python report.py @($args) }                                    # .docx 보고서 생성
    "serve"  { python server.py 8000 }                                        # UI 서버 → localhost:8000
    "check"  { python check_keys.py }                                         # Gemini/Voyage 키 연동 진단
    "review" { python review.py @($args) }                                    # 검수·데이터관리(목록/상태변경/이력)
    default  { python etl.py; python ingest.py "../data/normalized.jsonl"; python demo.py }
}
