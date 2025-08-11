# -*- coding: utf-8 -*-
"""
Простое долговременное хранилище контекста по пользователю (без БД).
Формат: data/sessions/{user_id}.json  => {history: [...], profile: {...}, updated_at: "..."}
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, List

DATA_DIR = Path(__file__).parent / "data" / "sessions"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _file(user_id: int) -> Path:
    return DATA_DIR / f"{user_id}.json"

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _load(user_id: int) -> Dict:
    fp = _file(user_id)
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"history": [], "profile": {}, "updated_at": _now()}

def _save(user_id: int, data: Dict) -> None:
    data["updated_at"] = _now()
    fp = _file(user_id)
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def append_message(user_id: int, role: str, content: str, *, cap: int = 50) -> None:
    """Добавить сообщение в историю (с ограничением длины)."""
    data = _load(user_id)
    data.setdefault("history", []).append({"role": role, "content": content})
    # кап истории
    if len(data["history"]) > cap:
        data["history"] = data["history"][-cap:]
    _save(user_id, data)

def get_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """Последние limit сообщений (без системных)."""
    data = _load(user_id)
    hist = data.get("history", [])
    return hist[-limit:] if limit else hist

def clear_history(user_id: int) -> None:
    data = _load(user_id)
    data["history"] = []
    _save(user_id, data)

def update_profile(user_id: int, **fields) -> Dict:
    """Обновить поля профиля (например: level='сад', org_number='27', ...)."""
    data = _load(user_id)
    prof = data.setdefault("profile", {})
    prof.update({k: v for k, v in fields.items() if v is not None})
    _save(user_id, data)
    return prof

def get_profile(user_id: int) -> Dict:
    return _load(user_id).get("profile", {})

def clear_profile(user_id: int) -> None:
    data = _load(user_id)
    data["profile"] = {}
    _save(user_id, data)
