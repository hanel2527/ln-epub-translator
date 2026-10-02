# ln-epub-translator: 라이트 노벨용 EPUB 번역기
![image-webui](./images/webui.png)

## 환경 설정 (uv 설치)
1. [uv 설치 가이드](https://docs.astral.sh/uv/getting-started/installation/)를 참고하여 `uv`를 설치

```sh
# Windows - cmd를 열고 다음 명령어를 실행
winget install --id=astral-sh.uv -e
# Linux, macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### webui 실행 (추천)
```sh
uv run scripts/run_webui.py
```
`http://localhost:2527` 를 브라우저에서 열기

추천 세팅:
- API Key: "your-actual-api-key-from-ai-studio"
- API URL: "https://generativelanguage.googleapis.com/v1/beta/openai/"
- MODEL: "gemini-3.1-flash-lite"

`Save Config` 버튼을 클릭해서 설정 저장.
epub파일 업로드한 다음 `Start Translation` 버튼을 눌러서 번역 시작.


## CLI (고급 사용자용)
### 설정 파일

1. `format.template.json` 파일을 `format.json`으로 복사
2. `"key"`, `"url"`, `"model"` 값을 실제 값으로 교체. openai랑 호환되는 API 사용 가능.

권장 설정:
```json
{
  "key": "ai-studio에서-발급받은-api키",
  "url": "https://generativelanguage.googleapis.com/v1beta/openai/",
  "model": "gemini-3.1-flash-lite",
  "token_encoding": "o200k_base",
  "timeout": 360.0,
  "retry_times": 10,
  "retry_interval_seconds": 0.75,
  "translation": {
    "temperature": 0.8,
    "top_p": 0.6
  },
  "fill": {
    "temperature": [0.2, 0.9],
    "top_p": [0.9, 1.0]
  },
  "study": {
    "max_output_tokens": 16384,
    "temperature": 0.3,
    "top_p": 0.9,
    "extra_body": null
  }
}
```

### 번역자 노트 / Dictionary (선택 사항)

이름 표기, 말투, 번역 지침 등을 자유롭게 적은 UTF-8 텍스트 파일을 `--dict`로 지정.
파일 전체를 파싱이나 재포맷 없이 LLM에 전달하므로 제목, 글머리 기호, `이름: 번역` 같은 형식을 맞출 필요 없음.
기존 Markdown 사전 파일도 그대로 사용 가능.

예를 들어 `notes.txt`에 다음처럼 작성:
```text
放虎原ひばり는 호코바루 히바리로 번역해줘.
馬剃天愛星는 바소리 티아라로 써줘.

1인칭 서술은 반말로 해줘.
대사는 자연스럽게 옮겨줘.
```

```sh
uv run scripts/translate_for_study.py path/to/book.epub --dict notes.txt -l Korean
```

예시는 [example.dict.md](../example.dict.md)

#### 이름 표기 범위와 번역 충실도
프롬프트에서 풀네임 사전 항목은 인물 식별과 표기 지침으로만 사용하도록 명시.
예를 들어 `温水和彦 = 누쿠미즈 카즈히코`여도 원문의 `温水`는 `누쿠미즈`, `和彦`는 `카즈히코`로만 번역하고, 풀네임은 원문에 풀네임이 있을 때만 사용하도록 지시.
같은 인물이라도 `이름 + 호칭`을 별명으로 바꾸지 않으며, 대명사·생략된 주어·직함을 인물 이름으로 채우지 않도록 함.

그 외에도 다음 지침을 적용:
- 대사와 속마음, 부정·추측·조건·수량, 누가 누구에게 무엇을 했는지 보존.
- 학습 설명은 해당 문단의 표현만 다루고, 반복되는 유용한 한자어도 짧게 다시 설명.
- 읽기와 문맥상 뜻을 우선하며, 확신 없는 한자 음훈·어원은 지어내지 않고 해당 세부 설명을 생략.

이것은 프롬프트 지침이지 이름 강제 치환이나 사전 검증 기능은 아님.
실제 `gemma4:31b`에서 한국어 18문단·영어 4문단 이름 범위 검증은 통과했지만, 별도 12문단 샘플에서는 반복 어휘 설명 하나가 여전히 누락됨.
특히 학습 설명은 검수가 필요. 새 요청부터 개선된 프롬프트를 사용하며, `--resume`으로 이미 완료한 챕터를 다시 번역하지는 않음.


### 번역 실행

```sh
uv run scripts/translate_for_study.py path/to/book.epub --dict path/to/dict.md -l Korean
# 번역 진행상황은 out 디렉토리에 저장됨. 진행상황은 out/<책 이름>/_progress.html 파일에서 확인 가능
# 중단된 지점에서 이어서 번역
uv run scripts/translate_for_study.py path/to/book.epub --dict path/to/dict.md -l Korean --resume
```

출력 파일은 `out` 디렉터리에 생성됨.

### 문단별 학습 설명
학습 번역은 JSON 대신 다음처럼 태그가 붙은 텍스트를 요청함:
```html
<p>번역을 배운다.</p> <study>翻訳(ほんやく): 翻(번역할 번) + 訳(번역할 역); '번역'을 뜻하는 한자어</study>
<p>조금 쉬자.</p>
```
원문 문단마다 같은 순서로 번역 `<p>` 하나와 필요한 만큼의 `<study>` 설명을 반환.
설명은 자유 문장이며 줄바꿈, 태그 대소문자, 설명의 닫는 태그 누락은 허용.
다만 번역문이 조용히 빠지거나 문단이 밀리지 않도록 번역 `<p>`는 내용과 닫는 태그가 있어야 하고 원문과 개수가 같아야 함.

- 학습 EPUB과 `_progress.html`: 후리가나가 붙은 원문 아래에 번역과 학습 설명을 나란히 표시. 긴 설명은 화면 폭에 맞게 줄바꿈.
- 번역 전용 EPUB: 원문이나 학습 설명 없이 번역문만 포함.
- 같은 단어가 다시 나와도 해당 문단에 설명 표시. 챕터 끝 요약은 제거.
- 미리보기의 책 전체 단어장과 어휘 통계는 `단어(읽기): 설명`으로 인식되는 항목만 집계. 다른 형식의 설명도 해당 문단에는 빠짐없이 표시.
- 번역 누락이나 불완전한 응답은 배치를 나눠 처리. 한 문단도 끝내 실패하면 완료로 저장하지 않고 오류로 중단.
- `--resume`은 이미 완료한 챕터의 저장된 출력을 유지. 기존 번역도 새 형식으로 보려면 `-o out-text`처럼 별도 출력 폴더에서 새로 번역.

요청당 출력 상한 기본값은 **16384 토큰**. `format.json`의 `study.max_output_tokens`로 변경할 수 있으며 Web UI도 같은 설정을 사용.
CLI에서는 다음 옵션이 설정 파일보다 우선:
```sh
uv run scripts/translate_for_study.py book.epub -l Korean --max-output-tokens 16384
```
사용하는 API가 지원하는 범위의 양의 정수로 지정. 상한을 늘려도 모델이 반드시 그만큼 길게 답하는 것은 아님.
출력 상한을 바꾸면 이전 상한으로 생성된 응답 캐시를 재사용하지 않음.

설명이 길어지면 `-b 1200 --max-paragraphs 12`부터 시작해 미리보기를 보며 조정하는 것을 권장.
큰 배치에서는 형식·내용 오류가 여전히 발생할 수 있음. 번역 문단이 이미 완결된 뒤의 `<study>`를 `</p>`로 잘못 닫는 경우는 허용.
모델이 작성한 한자 읽기·음훈·어원 설명은 별도 검수가 필요.

Ollama `gemma4:31b` 실측: 작성한 30문단을 두 번 이어 붙인 60문단·5198자 길이 테스트에서,
4096 상한은 44문단 번역 후 `length`로 잘렸고 16384 상한은 5734 토큰을 사용해 60문단을 모두 번역하고 `stop`으로 종료.
다만 반복된 후반부의 학습 설명은 생략했으며, 30문단 테스트에서는 한자 음훈·어원 오류도 발견.
출력 여유를 확보해도 작은 배치와 내용 검수를 대체하지는 못함.

Ollama Cloud의 OpenAI 호환 주소는 `https://ollama.com/v1`이며 `/api/v1`이 아님.
([공식 문서](https://docs.ollama.com/api/openai-compatibility))

### 결과물
```sh
out
├── <책 이름>
│   ├── logs
│   │   ├── request 2026-06-21 02-39-23.log
│   │   ├── request 2026-06-21 02-39-26.log
...
│   │   ├── request 2026-06-21 02-48-28.log
│   │   └── request 2026-06-21 02-48-42.log
│   ├── _progress.html
│   ├── _state.json
│   ├── translated_study.epub
│   └── translated_study.clean.epub
```
- _progress.hmtl: 진행상황 확인용
- translated_study.epub: 원문 + 번역문이 있는 epub 파일
- translated_study.clean.epub: 번역문만 있는 epub 파일