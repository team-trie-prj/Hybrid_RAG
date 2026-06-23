# 설정 가이드 — 공공데이터 API & Gemini 불러오기

키 없이도 오프라인으로 동작하지만, 아래를 설정하면 **실데이터 + 실LLM**으로 승격된다.

---

## 1. 공공데이터포털(data.go.kr) API 가져오기

### 방법 A — 파일(CSV) 다운로드  ← 가장 간단, 권장
대부분의 통계 데이터셋은 파일로 제공된다.
1. [data.go.kr](https://www.data.go.kr) 회원가입 / 로그인
2. 원하는 데이터셋 검색 → 상세 페이지에서 **CSV 다운로드** (로그인만 하면 됨)
3. `data/raw/`에 저장하고, `data/datasets/registry.json`에 매핑 config 1개 추가
   (컬럼명만 맞추면 됨 — 코드 수정 불필요)
4. `.\run.ps1 etl`  → 정규화 + 적재

### 방법 B — 오픈API (인증키 필요)
1. data.go.kr 로그인 → 데이터셋 상세에서 **[활용신청]** 클릭 → 활용목적 입력 → 신청
   - 자동승인되는 경우가 많고, 보통 즉시~1시간 내 사용 가능
2. **마이페이지 > 데이터활용 > 인증키 발급 현황**에서 `일반 인증키(serviceKey)` 복사
3. 환경변수 등록 (PowerShell):
   ```powershell
   $env:DATAGO_SERVICE_KEY = "발급받은_serviceKey"
   ```
4. `data/datasets/registry.json`의 해당 config에 `api` 블록 추가:
   ```json
   "api": {
     "endpoint": "데이터셋 페이지의 '요청주소'",
     "params": {"추가파라미터": "값"},
     "items_path": ["response", "body", "items", "item"]
   }
   ```
5. 수집 → 적재:
   ```powershell
   .\run.ps1 loadapi 15130420     # 특정 dataset_id
   .\run.ps1 loadapi --all        # api 블록 있는 모든 데이터셋
   ```

> Decoding 키를 쓰면 requests가 자동 인코딩한다. 호출 코드는 `src/datago_client.py` 참고.

---

## 2. Gemini 3.5 Flash 불러오기

### 키 발급
1. [Google AI Studio](https://aistudio.google.com/app/apikey) 접속 (구글 계정 로그인)
2. **[Get API key] → [Create API key]** 클릭 → 키 복사

### 설정
```powershell
$env:GEMINI_API_KEY = "발급받은_API_KEY"     # 또는 GOOGLE_API_KEY
# (선택) 모델 변경:  $env:GEMINI_MODEL = "gemini-3.5-flash"
```

### 동작 확인
```powershell
.\run.ps1 ask 전국에서 화재가 가장 많은 지역은?
```
- 키가 있으면 응답 상단에 폴백 안내문이 사라지고 Gemini가 직접 도구를 호출한다.
- 키가 없으면 자동으로 규칙 라우터로 폴백한다(데모는 그대로 동작).

> 라이브러리 설치: `pip install -r requirements.txt` (google-genai 포함)
> 코드: `src/llm.py` (function-calling 루프), 모델 ID 기본값 `gemini-3.5-flash`.

---

## 3. (선택) 임베딩 품질 향상 — Voyage
로컬 해시 임베딩 대신 의미 임베딩을 쓰려면:
```powershell
$env:VOYAGE_API_KEY = "발급키"   # https://www.voyageai.com
.\run.ps1 etl                    # 재적재 시 voyage-3 임베딩 사용
```

---

## 한눈에 보기

| 환경변수 | 용도 | 없을 때 |
|---|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini 3.5 Flash 에이전트 | 규칙 라우터 폴백 |
| `DATAGO_SERVICE_KEY` | data.go.kr 오픈API 수집 | CSV 수동 적재 사용 |
| `VOYAGE_API_KEY` | Voyage 임베딩 | 로컬 해시 임베딩 |
