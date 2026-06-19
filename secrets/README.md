# Google Cloud TTS credentials

Google Cloud Text-to-Speech 서비스 계정 JSON 파일을 이 폴더에 넣으세요.

1. `google-tts.json.example`를 복사해 `google-tts.json`으로 저장
2. 발급받은 서비스 계정 키 값으로 내용을 채우기

```text
cp google-tts.json.example google-tts.json
```

주의:
- 실제 `google-tts.json`은 `.gitignore`(secrets/*.json)로 추적 제외됩니다.
- 실제 키 파일은 Git/ZIP/메신저 등 어떤 공유 대상에도 절대 포함하지 마세요.
- 키가 한 번이라도 노출되면 즉시 **폐기 후 재발급**하세요.
