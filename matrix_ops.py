from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

CONFIG_PATH = Path(os.environ.get("INSTANCE_CONFIG", "/config/instances.json"))
TOKEN_ROOT = Path("/data/tokens")
TOKEN_ROOT.mkdir(parents=True, exist_ok=True)

SERVICE_ADMIN_DISPLAY_NAME = os.environ.get(
    "SERVICE_ADMIN_DISPLAY_NAME", "Matrix Admin Service"
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[A-Za-z]{2,63}$"
)
LOCALPART_RE = re.compile(r"^[a-z0-9._=-]{1,64}$")


@dataclass
class MatrixInstance:
    slug: str
    name: str
    chat_domain: str
    rtc_domain: str
    synapse_container: str
    postgres_container: str = ""
    internal_url_override: str = ""
    is_primary: bool = False


def run(args, timeout=60):
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=True,
    ).stdout


def _validate_instance(raw, index):
    if not isinstance(raw, dict):
        raise RuntimeError(f"Instance #{index}: objet JSON attendu.")

    slug = str(raw.get("slug", "")).strip().lower()
    name = str(raw.get("name", "")).strip()
    chat = str(raw.get("chat_domain", "")).strip().lower()
    rtc = str(raw.get("rtc_domain", "")).strip().lower()
    synapse = str(raw.get("synapse_container", "")).strip()
    postgres = str(raw.get("postgres_container", "")).strip()
    internal = str(raw.get("internal_url", "")).strip()
    primary = bool(raw.get("primary", False))

    if not SLUG_RE.fullmatch(slug):
        raise RuntimeError(f"Instance #{index}: slug invalide.")
    if not name or len(name) > 100:
        raise RuntimeError(f"Instance {slug}: nom invalide.")
    if not DOMAIN_RE.fullmatch(chat):
        raise RuntimeError(f"Instance {slug}: chat_domain invalide.")
    if rtc and not DOMAIN_RE.fullmatch(rtc):
        raise RuntimeError(f"Instance {slug}: rtc_domain invalide.")
    if not synapse:
        raise RuntimeError(f"Instance {slug}: synapse_container obligatoire.")
    if internal and not internal.startswith(("http://", "https://")):
        raise RuntimeError(f"Instance {slug}: internal_url doit commencer par http:// ou https://.")

    return MatrixInstance(
        slug=slug,
        name=name,
        chat_domain=chat,
        rtc_domain=rtc,
        synapse_container=synapse,
        postgres_container=postgres,
        internal_url_override=internal,
        is_primary=primary,
    )


def get_instances():
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"Configuration introuvable : {CONFIG_PATH}. "
            "Copiez config/instances.example.json vers config/instances.json."
        )

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Configuration JSON invalide : {exc}") from exc

    if not isinstance(data, list) or not data:
        raise RuntimeError("instances.json doit contenir une liste non vide.")

    instances = [_validate_instance(raw, i + 1) for i, raw in enumerate(data)]

    slugs = [i.slug for i in instances]
    if len(slugs) != len(set(slugs)):
        raise RuntimeError("Chaque instance doit avoir un slug unique.")

    if not any(i.is_primary for i in instances):
        instances[0].is_primary = True

    return instances


def get_instance(slug):
    slug = (slug or "").strip().lower()
    return next((x for x in get_instances() if x.slug == slug), None)


def state(name):
    if not name:
        return {"status": "non-configuré", "health": "-"}
    try:
        x = run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}",
                name,
            ]
        ).strip()
        a, b = (x.split("|", 1) + ["-"])[:2]
        return {"status": a, "health": b}
    except Exception:
        return {"status": "absent", "health": "-"}


def instance_status(i):
    return {
        "synapse": state(i.synapse_container),
        "postgres": state(i.postgres_container),
    }


def internal_url(i):
    if i.internal_url_override:
        return i.internal_url_override.rstrip("/")
    return f"http://{i.synapse_container}:8008"


def token_path(i):
    return TOKEN_ROOT / f"{i.slug}.json"


def create_service_admin(i):
    user = f"portal-admin-{secrets.token_hex(4)}"
    pwd = secrets.token_urlsafe(36)

    x = run(
        [
            "docker",
            "exec",
            i.synapse_container,
            "register_new_matrix_user",
            "-u",
            user,
            "-p",
            pwd,
            "-a",
            "-c",
            "/data/homeserver.yaml",
            "http://localhost:8008",
        ],
        90,
    )
    if "ERROR" in x.upper():
        raise RuntimeError("Création du compte de service impossible.")

    url = internal_url(i)
    r = requests.post(
        url + "/_matrix/client/v3/login",
        json={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user},
            "password": pwd,
        },
        timeout=20,
    )
    r.raise_for_status()

    token = r.json()["access_token"]
    uid = f"@{user}:{i.chat_domain}"

    try:
        requests.put(
            f"{url}/_synapse/admin/v2/users/{quote(uid, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "admin": True,
                "user_type": "support",
                "displayname": SERVICE_ADMIN_DISPLAY_NAME,
            },
            timeout=20,
        ).raise_for_status()
    except Exception:
        # Le compte reste administrateur même si la personnalisation échoue.
        pass

    data = {"user_id": uid, "access_token": token}
    p = token_path(i)
    p.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(p, 0o600)
    return data


def service_admin(i):
    p = token_path(i)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data
        except Exception:
            p.unlink(missing_ok=True)
    return create_service_admin(i)


def admin_request(i, method, path, **kwargs):
    data = service_admin(i)
    url = internal_url(i) + path

    def call(tok):
        headers = dict(kwargs.get("headers") or {})
        headers["Authorization"] = f"Bearer {tok}"
        opts = dict(kwargs)
        opts["headers"] = headers
        return requests.request(method, url, timeout=30, **opts)

    r = call(data["access_token"])
    if r.status_code in (401, 403):
        token_path(i).unlink(missing_ok=True)
        r = call(create_service_admin(i)["access_token"])
    return r


def list_users(i):
    users = []
    offset = 0

    while True:
        r = admin_request(
            i,
            "GET",
            "/_synapse/admin/v2/users",
            params={"from": offset, "limit": 100},
        )
        r.raise_for_status()
        body = r.json()
        batch = body.get("users") or []

        for item in batch:
            uid = (item.get("name") or "").strip()
            if not uid or uid.startswith("@portal-admin-"):
                continue
            users.append(
                {
                    "id": uid,
                    "role": "ADMIN" if item.get("admin") else "USER",
                    "status": "DESACTIVE" if item.get("deactivated") else "ACTIF",
                }
            )

        next_token = body.get("next_token")
        if next_token is None:
            break
        try:
            offset = int(next_token)
        except Exception:
            break

    return sorted(users, key=lambda x: x["id"].lower())


def add_user(i, localpart, display_name, password, make_admin=False):
    localpart = localpart.strip().lower()
    if not LOCALPART_RE.fullmatch(localpart):
        raise ValueError("Identifiant invalide.")
    if not display_name.strip() or "\n" in display_name or "\r" in display_name:
        raise ValueError("Nom affiché invalide.")
    if len(password) < 8 or "\n" in password or "\r" in password:
        raise ValueError("Mot de passe : 8 caractères minimum.")

    flag = "-a" if make_admin else "--no-admin"
    x = run(
        [
            "docker",
            "exec",
            i.synapse_container,
            "register_new_matrix_user",
            "-u",
            localpart,
            "-p",
            password,
            flag,
            "-c",
            "/data/homeserver.yaml",
            "http://localhost:8008",
        ],
        90,
    )
    if "ERROR" in x.upper():
        raise RuntimeError(x.strip())

    url = internal_url(i)
    r = requests.post(
        url + "/_matrix/client/v3/login",
        json={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": localpart},
            "password": password,
        },
        timeout=20,
    )
    r.raise_for_status()
    tok = r.json().get("access_token")
    uid = f"@{localpart}:{i.chat_domain}"

    r = requests.put(
        f"{url}/_matrix/client/v3/profile/{quote(uid, safe='')}/displayname",
        headers={"Authorization": f"Bearer {tok}"},
        json={"displayname": display_name.strip()},
        timeout=20,
    )
    r.raise_for_status()
    return uid


def deactivate_user(i, user_id, erase=False):
    if not user_id.startswith("@") or ":" not in user_id:
        raise ValueError("Identifiant Matrix invalide.")
    if user_id.startswith("@portal-admin-"):
        raise ValueError("Compte de service protégé.")

    r = admin_request(
        i,
        "POST",
        f"/_synapse/admin/v1/deactivate/{quote(user_id, safe='')}",
        json={"erase": bool(erase)},
    )
    r.raise_for_status()
    return r.json() if r.content else {}


def reactivate_user(i, user_id, new_password):
    if not user_id.startswith("@") or ":" not in user_id:
        raise ValueError("Identifiant Matrix invalide.")
    if user_id.startswith("@portal-admin-"):
        raise ValueError("Compte de service protégé.")
    if len(new_password) < 8 or "\n" in new_password or "\r" in new_password:
        raise ValueError("Mot de passe : 8 caractères minimum.")

    r = admin_request(
        i,
        "PUT",
        f"/_synapse/admin/v2/users/{quote(user_id, safe='')}",
        json={"deactivated": False, "password": new_password},
    )
    r.raise_for_status()
    return r.json() if r.content else {}


def erase_user(i, user_id):
    """
    Efface le compte avec erase=true sans supprimer les messages ou fichiers
    déjà partagés dans les salons.
    """
    if not user_id.startswith("@") or ":" not in user_id:
        raise ValueError("Identifiant Matrix invalide.")
    if user_id.startswith("@portal-admin-"):
        raise ValueError("Compte de service protégé.")

    deactivation = deactivate_user(i, user_id, erase=True)
    return {
        "deactivation": deactivation,
        "history_preserved": True,
        "messages_deleted": 0,
        "media_deleted": 0,
    }


def reset_password(i, user_id, new_password, logout_devices=True):
    if not user_id.startswith("@") or ":" not in user_id:
        raise ValueError("Identifiant Matrix invalide.")
    if len(new_password) < 8 or "\n" in new_password or "\r" in new_password:
        raise ValueError("Mot de passe : 8 caractères minimum.")

    r = admin_request(
        i,
        "POST",
        f"/_synapse/admin/v1/reset_password/{quote(user_id, safe='')}",
        json={
            "new_password": new_password,
            "logout_devices": bool(logout_devices),
        },
    )
    r.raise_for_status()
    return r.json() if r.content else {}
