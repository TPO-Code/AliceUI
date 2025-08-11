# app/core/conversation_manager.py
from __future__ import annotations
import base64, json, os, time, uuid, hashlib
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend


@dataclass
class ConversationMeta:
    id: str
    title: str
    created_ts: float
    updated_ts: float
    is_new: bool = True  # “new” means no user/assistant messages yet

class ConversationManager:
    """
    Encrypted, single-user conversation store.

    Layout (under data_dir):
      conversations/
        index.json           # plaintext: ids, titles, timestamps, password verifier
        <id>.json.enc        # encrypted payload: {"system": str, "messages":[{role,content},...]}
    """
    INDEX_NAME = "index.json"
    SUBDIR = "conversations"
    KDF_ITER = 200_000
    VERIFIER_LABEL = "password_verifier"  # hex sha256 of derived key (not the password)
    SALT_LEN = 16

    def __init__(self, data_dir: str):
        self.data_dir = os.path.abspath(data_dir)
        self.root = os.path.join(self.data_dir, self.SUBDIR)
        os.makedirs(self.root, exist_ok=True)
        self.index_path = os.path.join(self.root, self.INDEX_NAME)
        self._index: Dict[str, Any] = {}
        self._fernet_cache: Dict[str, Fernet] = {}  # id -> fernet
        self._derived_key: Optional[bytes] = None
        self._loaded = False
        self._current_id: Optional[str] = None

    # ---------- Public API ----------

    def ensure_loaded(self):
        if self._loaded:
            return
        if os.path.exists(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as f:
                self._index = json.load(f)
        else:
            self._index = {"version": 1, "conversations": [], self.VERIFIER_LABEL: None}
            self._save_index()
        self._loaded = True

    def has_password(self) -> bool:
        self.ensure_loaded()
        return bool(self._index.get(self.VERIFIER_LABEL))

    def set_master_password(self, password: str):
        """Sets/validates master password. If index has a verifier, we validate it; else we set it."""
        self.ensure_loaded()
        if not password:
            raise ValueError("Master password cannot be empty.")
        # derive a deterministic key from the password and a fixed, index-level salt
        salt_path = os.path.join(self.root, ".index.salt")
        if not os.path.exists(salt_path):
            with open(salt_path, "wb") as f:
                f.write(os.urandom(self.SALT_LEN))
        with open(salt_path, "rb") as f:
            idx_salt = f.read()

        derived = self._derive_key(password.encode("utf-8"), idx_salt)
        verifier = hashlib.sha256(derived).hexdigest()

        existing = self._index.get(self.VERIFIER_LABEL)
        if existing and existing != verifier:
            raise ValueError("Incorrect master password.")
        if not existing:
            self._index[self.VERIFIER_LABEL] = verifier
            self._save_index()
        self._derived_key = derived  # cache

    def list(self) -> List[ConversationMeta]:
        self.ensure_loaded()
        return [ConversationMeta(**c) for c in self._index.get("conversations", [])]

    def get_current_id(self) -> Optional[str]:
        return self._current_id

    def create(self, title: str = "New conversation") -> ConversationMeta:
        self._require_key()
        cid = str(uuid.uuid4())
        now = time.time()
        meta = ConversationMeta(id=cid, title=title, created_ts=now, updated_ts=now, is_new=True)
        self._index.setdefault("conversations", []).insert(0, asdict(meta))  # most recent first
        self._save_index()
        # bootstrap encrypted file
        self._write_payload(cid, {"system": "", "messages": []})
        self._current_id = cid
        return meta

    def rename(self, conv_id: str, new_title: str):
        self.ensure_loaded()
        for c in self._index["conversations"]:
            if c["id"] == conv_id:
                c["title"] = new_title or c["title"]
                c["updated_ts"] = time.time()
                self._save_index()
                return
        raise KeyError("Conversation not found")

    def delete(self, conv_id: str):
        self.ensure_loaded()
        self._index["conversations"] = [c for c in self._index["conversations"] if c["id"] != conv_id]
        self._save_index()
        p = self._enc_path(conv_id)
        if os.path.exists(p):
            os.remove(p)
        if self._current_id == conv_id:
            self._current_id = None

    def load(self, conv_id: str) -> Dict[str, Any]:
        """Returns payload: {'system': str, 'messages': list}"""
        self._require_key()
        data = self._read_payload(conv_id)
        self._current_id = conv_id
        return data

    def load_or_create_latest(self) -> Tuple[ConversationMeta, Dict[str, Any]]:
        self._require_key()
        items = self.list()
        if not items:
            meta = self.create("New conversation")
            return meta, {"system": "", "messages": []}
        meta = items[0]
        payload = self.load(meta.id)
        return meta, payload

    def set_system(self, conv_id: str, system_text: str):
        payload = self._read_payload(conv_id)
        payload["system"] = system_text or ""
        self._write_payload(conv_id, payload)
        self._touch(conv_id, is_new_flag=self._is_new(payload))

    def append_message(self, conv_id: str, role: str, content: str):
        payload = self._read_payload(conv_id)
        payload.setdefault("messages", []).append({"role": role, "content": content})
        self._write_payload(conv_id, payload)
        self._touch(conv_id, is_new_flag=self._is_new(payload))

    def replace_messages(self, conv_id: str, messages: List[Dict[str, str]]):
        payload = self._read_payload(conv_id)
        payload["messages"] = messages[:]
        self._write_payload(conv_id, payload)
        self._touch(conv_id, is_new_flag=self._is_new(payload))

    # ---------- Internals ----------

    def _require_key(self):
        if self._derived_key is None:
            raise RuntimeError("Master password not set. Call set_master_password() first.")

    def _save_index(self):
        os.makedirs(self.root, exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

    def _enc_path(self, conv_id: str) -> str:
        return os.path.join(self.root, f"{conv_id}.json.enc")

    def _derive_key(self, pwd: bytes, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.KDF_ITER,
            backend=default_backend(),
        )
        return kdf.derive(pwd)

    def _get_fernet(self, conv_id: str) -> Tuple[Fernet, bytes]:
        if conv_id in self._fernet_cache:
            return self._fernet_cache[conv_id], b""
        # per-file salt
        salt_path = os.path.join(self.root, f"{conv_id}.salt")
        if not os.path.exists(salt_path):
            with open(salt_path, "wb") as f:
                f.write(os.urandom(self.SALT_LEN))
        with open(salt_path, "rb") as f:
            salt = f.read()
        key = self._derive_key(self._derived_key, salt)  # derive from master-derived key + per-file salt
        fkey = base64.urlsafe_b64encode(key)
        fernet = Fernet(fkey)
        self._fernet_cache[conv_id] = fernet
        return fernet, salt

    def _read_payload(self, conv_id: str) -> Dict[str, Any]:
        fernet, _ = self._get_fernet(conv_id)
        p = self._enc_path(conv_id)
        if not os.path.exists(p):
            return {"system": "", "messages": []}
        with open(p, "rb") as f:
            token = f.read()
        raw = fernet.decrypt(token)
        return json.loads(raw.decode("utf-8"))

    def _write_payload(self, conv_id: str, payload: Dict[str, Any]):
        fernet, _ = self._get_fernet(conv_id)
        token = fernet.encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        with open(self._enc_path(conv_id), "wb") as f:
            f.write(token)

    def _touch(self, conv_id: str, *, is_new_flag: bool):
        now = time.time()
        for c in self._index["conversations"]:
            if c["id"] == conv_id:
                c["updated_ts"] = now
                c["is_new"] = bool(is_new_flag)
                break
        # keep most recent first
        self._index["conversations"].sort(key=lambda c: c["updated_ts"], reverse=True)
        self._save_index()

    def _is_new(self, payload: Dict[str, Any]) -> bool:
        # "new" means no non-system messages (empty or only system)
        msgs = payload.get("messages") or []
        return len([m for m in msgs if m.get("role") in ("user", "assistant")]) == 0
