# lecture-to-md

강의 PDF를 **요약하지 않고, 원문 내용과 순서를 보존하는 구조화된 Markdown**으로 옮기기 위한 AI 에이전트 스킬입니다.

문장·표·수식·그림을 페이지별로 보존하고, 검색·인용·복습에 사용할 수 있도록 `## [p.N]` 앵커와 메타데이터를 붙입니다. Markdown을 읽는 도구에서 사용할 수 있으며, Obsidian은 선택 사항입니다.

> 이 프로젝트는 AI 에이전트가 읽는 작업 지침과 보조 스크립트입니다. 스크립트만 실행하면 완성된 Markdown이 자동 생성되는 변환기는 아닙니다. 무손실 보존은 작업 목표이며, 검증기의 PASS가 원문과의 완전한 일치를 보장하지 않습니다.

## 주요 기능

- 텍스트 PDF·스캔본의 페이지 렌더링과 텍스트 초안 추출
- 페이지별 `pure_text` / `needs_image` / `ambiguous` 분류
- 표를 Markdown으로, 수식을 LaTeX로 옮기는 판독 규칙
- 형태·색·공간관계 자체가 정보인 그림의 선택적 보존
- 페이지 앵커·메타데이터·이미지 링크·표·수식·내용 누락 의심 검사
- 위험도 기반 표본 재검토와 판독 불확실성 표시

## 필요한 환경

- Python **3.9 이상**. 이번 배포본은 Python 3.9와 3.12에서 검사했습니다.
- [Poppler](https://poppler.freedesktop.org/) 명령: `pdftoppm`, `pdftotext`, `pdfimages`, `pdfinfo`
- Python 패키지 Pillow, numpy — `requirements.txt`에 포함되어 있습니다.
- 로컬 파일·터미널을 다루고 페이지 이미지를 실제로 열어 볼 수 있는 AI 에이전트

에이전트의 모델·이미지 열람 기능에 따라 판독 품질과 비용이 달라집니다. 이 스킬 자체에는 API 키나 특정 모델 SDK가 필요하지 않습니다. 모델 이용 비용은 사용 중인 서비스에 따릅니다.

## 설치

저장소를 내려받아 압축을 푼 뒤, `SKILL.md`·`scripts/`·`references/`가 모두 들어 있는 `lecture-to-md` 폴더 전체를 사용 중인 에이전트의 스킬 위치에 등록합니다. 등록 경로는 해당 에이전트 설정에 따릅니다. `SKILL.md` 하나만 복사하면 보조 스크립트와 규칙 파일을 사용할 수 없습니다.

아래 명령은 `lecture-to-md` 폴더에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Poppler 설치 예시:

```bash
# macOS (Homebrew)
brew install poppler
```

```bash
# Ubuntu / Debian
sudo apt-get install poppler-utils
```

위 명령은 macOS·Linux용입니다. Windows에서는 Python과 Poppler를 별도로 설치하고, 가상환경 활성화 명령을 환경에 맞춰 바꿔야 합니다. Windows 실행은 이번 배포에서 검증하지 않았습니다.

에이전트가 스크립트를 실행할 때도 해당 가상환경의 Python을 사용하도록 설정합니다. `SKILL.md`의 명령은 `python3`로 표기되어 있으며, 활성화된 가상환경에서는 보통 해당 실행 파일을 가리킵니다. 에이전트의 각 셸 실행이 분리되어 있다면 가상환경 Python의 전체 경로를 사용합니다.

## 사용 예시

등록한 스킬을 사용할 수 있는 에이전트에 다음처럼 요청합니다.

```text
lecture-to-md 스킬로 첨부한 강의 PDF를 Markdown으로 변환해 줘.
요약하거나 문장을 고치지 말고 표·수식·그림을 보존해 줘.
출력은 내가 지정한 폴더에 저장하고, 기계 검증과 표본 재검토까지 해 줘.
```

출력 경로를 지정하지 않으면 기본적으로 원본 PDF와 같은 폴더에 저장합니다. 과목별 자료 폴더에 맞추는 기능은 요청한 경우에 사용할 수 있습니다. 세부 규칙은 [출력 위치·파일명 규칙](references/output_rules.md)을 참고하세요.

## 처리 흐름

1. 페이지 렌더링·텍스트 초안·이미지 후보를 추출합니다.
2. 페이지의 이미지 판독 필요성과 위험도를 분류합니다.
3. 에이전트가 원문을 옮기고 표·수식·그림을 대조합니다.
4. 메타데이터를 작성하고 기계 검증을 실행합니다.
5. 위험도가 높은 페이지를 이미지와 다시 대조합니다.

보조 스크립트 실행 예시입니다. 입력 PDF·추출작업폴더·완성 md 경로를 실제 경로로 바꿔 실행합니다. 아래의 `/tmp/lecture-to-md-work`는 **비어 있는 문서별 임시 폴더**를 사용하세요.

```bash
python3 scripts/render_pdf_pages.py input.pdf /tmp/lecture-to-md-work
python3 scripts/classify_pages.py /tmp/lecture-to-md-work

# 이 사이에 에이전트가 페이지를 판독하고 output.md를 작성합니다.

python3 scripts/validate_output.py output.md /tmp/lecture-to-md-work \
  --json /tmp/lecture-to-md-work/validation_report.json
```

추출 폴더에는 `pages/`, `text/`, 이미지 후보 `images/`, `manifest.json`, `classification.json`이 생깁니다. manifest에는 로컬 입력·작업 경로가 들어가므로 개인 작업 산출물로 관리합니다. 7단계 재검토가 끝나기 전에는 추출 폴더를 지우지 않습니다.

## 검증 결과 해석

| 종료 코드 | 의미 | 다음 행동 |
|---|---|---|
| `0` PASS | 구조 문제·기계적으로 탐지된 누락 의심 없음 | 필수 표본 재검토 수행 |
| `1` FAIL | 앵커·메타데이터·링크·표·수식 등의 구조 문제 | 수정 후 재검증 |
| `2` REVIEW | 텍스트 초안 대비 내용 누락 의심 | 해당 페이지 이미지를 열어 대조 |

`--ack`는 이미 이미지를 열어 대조한 REVIEW 페이지를 기록할 때만 사용합니다. 스캔본은 텍스트 초안과의 내용 비교가 어려우므로 이미지 대조가 필수입니다. 숫자 오기·표 셀 뒤바뀜 등은 검사기가 놓칠 수 있습니다.

현재 검증기는 `\left\{` 같은 이스케이프 중괄호를 포함한 일부 수식을 잘못 경고할 수 있습니다. 원문과 대조하고, 필요한 경우 의미가 같은 `cases` 환경 등으로 표기합니다. 원문에 없는 내용을 추가해 검증을 통과시키지 않습니다.

## 구성

```text
lecture-to-md/
├── SKILL.md
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── render_pdf_pages.py
│   ├── classify_pages.py
│   ├── validate_output.py
│   ├── compress_image.py
│   ├── crop_image.py
│   └── render_page.py
└── references/
    ├── transcription_rules.md
    ├── figures_and_scans.md
    ├── verification.md
    ├── large_documents.md
    ├── output_rules.md
    └── md_template.md
```

운영에 필요한 여섯 스크립트를 포함합니다. 개인 실사용 기록·인수인계 문서·기존 Git 이력·비공개 평가용 강의 PDF와 변환본은 배포하지 않습니다. `md_template.md`는 가상의 출력 형식을 설명하는 예시입니다.

## GitHub에 게시하기

이 사본은 기존 저장소의 `.git`과 이력을 포함하지 않습니다. GitHub에서 새 저장소를 만든 뒤 **이 폴더 안의 파일과 하위 폴더**를 저장소 루트에 올리면 됩니다. ZIP 파일만 올리면 README나 스킬 본문을 바로 탐색하기 어려우므로, 압축을 풀어 파일들을 올리는 방식을 권합니다.

터미널에서 push하는 경우 새 저장소는 README·라이선스·gitignore 자동 생성 없이 빈 상태로 만들고, 이 사본에서 새로 `git init`합니다. 커밋 작성자 이름·이메일은 공개되어도 되는 값을 사용합니다. 절차는 [GitHub 공식 안내](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)를 참고하세요.

`.gitignore`는 PDF·개인 작업 폴더·가상환경 등의 실수 추가를 줄이기 위한 기본값입니다. 모든 개인정보를 자동 탐지하지 않으며, 이미 커밋된 파일이나 과거 이력을 제거하지 않습니다.

## 라이선스

[MIT License](LICENSE). 코드와 스킬 문서에 적용됩니다. 변환 대상 강의자료와 그림의 권리는 원저작자에게 있으며, 이 저장소의 라이선스가 해당 자료에 대한 이용·재배포 권리를 부여하지는 않습니다.
