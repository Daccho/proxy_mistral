```
uv run python -m src.main join "https://meet.google.com/vdm-cqui-qsu"
```

lsof -ti:8765 2>/dev/null | xargs kill -9 2>/dev/null; pkill -9 ngrok 2>/dev/null; rm -f debug*tts*\*.wav; echo "cleaned"
