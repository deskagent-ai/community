# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Config-Verschluesselung mit Company Key.

Verwendung:
    # Key generieren
    python -m scripts.encryption --generate-key

    # Key auf diesem Rechner setzen
    python -m scripts.encryption --set-key ACME-xK9mP4qL7...

    # Config verschluesseln (fuer Verteilung)
    python -m scripts.encryption --encrypt config/apis.json

    # Alle verschluesselbaren Configs auflisten
    python -m scripts.encryption --list

Note: This module uses print() for CLI output since it's designed to be run
as a standalone command-line tool. system_log is not used here intentionally.
"""

import argparse
import json
import secrets
import sys
from pathlib import Path

# Pfade
SCRIPT_DIR = Path(__file__).parent
DESKAGENT_DIR = SCRIPT_DIR.parent
PROJECT_DIR = DESKAGENT_DIR.parent


def generate_key() -> str:
    """Generiert einen neuen Company Key."""
    # 32 zufaellige Bytes als URL-safe Base64
    key = secrets.token_urlsafe(32)
    return f"DESK-{key[:32]}"


def set_key(company_key: str) -> bool:
    """Speichert Company Key im Windows Credential Manager."""
    try:
        import keyring
        keyring.set_password("deskagent", "company_key", company_key)
        print(f"[OK] Company Key gespeichert im Credential Manager")
        return True
    except ImportError:
        print("[ERROR] keyring nicht installiert: pip install keyring")
        return False
    except Exception as e:
        print(f"[ERROR] Konnte Key nicht speichern: {e}")
        return False


def get_key() -> str:
    """Holt Company Key aus Windows Credential Manager."""
    try:
        import keyring
        return keyring.get_password("deskagent", "company_key")
    except ImportError:
        return None


def encrypt_file(input_path: Path, output_path: Path = None, company_key: str = None) -> bool:
    """
    Verschluesselt eine JSON-Datei.

    Args:
        input_path: Pfad zur JSON-Datei
        output_path: Pfad fuer verschluesselte Datei (default: .enc statt .json)
        company_key: Company Key (default: aus Credential Manager)
    """
    try:
        from cryptography.fernet import Fernet
        import base64
        import hashlib

        # Key holen
        if not company_key:
            company_key = get_key()
        if not company_key:
            print("[ERROR] Kein Company Key. Bitte mit --set-key setzen.")
            return False

        # Output-Pfad
        if not output_path:
            output_path = input_path.with_suffix(".enc")

        # JSON laden und validieren
        content = input_path.read_text(encoding="utf-8")
        json.loads(content)  # Validierung

        # Key ableiten (32 bytes fuer Fernet)
        key = base64.urlsafe_b64encode(
            hashlib.sha256(company_key.encode()).digest()
        )

        # Verschluesseln
        fernet = Fernet(key)
        encrypted = fernet.encrypt(content.encode("utf-8"))

        # Speichern
        output_path.write_bytes(encrypted)
        print(f"[OK] Verschluesselt: {input_path.name} -> {output_path.name}")
        return True

    except ImportError:
        print("[ERROR] cryptography nicht installiert: pip install cryptography")
        return False
    except json.JSONDecodeError:
        print(f"[ERROR] Ungueltige JSON-Datei: {input_path}")
        return False
    except Exception as e:
        print(f"[ERROR] Verschluesselung fehlgeschlagen: {e}")
        return False


def decrypt_file(input_path: Path, output_path: Path = None, company_key: str = None) -> bool:
    """
    Entschluesselt eine .enc Datei.

    Args:
        input_path: Pfad zur .enc Datei
        output_path: Pfad fuer entschluesselte Datei (default: .json statt .enc)
        company_key: Company Key (default: aus Credential Manager)
    """
    try:
        from cryptography.fernet import Fernet
        import base64
        import hashlib

        # Key holen
        if not company_key:
            company_key = get_key()
        if not company_key:
            print("[ERROR] Kein Company Key. Bitte mit --set-key setzen.")
            return False

        # Output-Pfad
        if not output_path:
            output_path = input_path.with_suffix(".json")

        # Key ableiten
        key = base64.urlsafe_b64encode(
            hashlib.sha256(company_key.encode()).digest()
        )

        # Entschluesseln
        fernet = Fernet(key)
        encrypted_data = input_path.read_bytes()
        decrypted = fernet.decrypt(encrypted_data)

        # Speichern
        output_path.write_text(decrypted.decode("utf-8"), encoding="utf-8")
        print(f"[OK] Entschluesselt: {input_path.name} -> {output_path.name}")
        return True

    except ImportError:
        print("[ERROR] cryptography nicht installiert: pip install cryptography")
        return False
    except Exception as e:
        print(f"[ERROR] Entschluesselung fehlgeschlagen: {e}")
        return False


def list_configs():
    """Listet alle Config-Dateien und deren Status."""
    config_dir = PROJECT_DIR / "config"

    print("\n=== Config-Dateien ===\n")

    for json_file in sorted(config_dir.glob("*.json")):
        enc_file = json_file.with_suffix(".enc")
        status = "verschluesselt" if enc_file.exists() else "Klartext"
        size = json_file.stat().st_size
        print(f"  {json_file.name:20} {size:>8} bytes  [{status}]")

    print()

    # Verschluesselte Dateien
    enc_files = list(config_dir.glob("*.enc"))
    if enc_files:
        print("Verschluesselte Dateien:")
        for enc_file in enc_files:
            size = enc_file.stat().st_size
            print(f"  {enc_file.name:20} {size:>8} bytes")
        print()

    # Key-Status
    key = get_key()
    if key:
        print(f"Company Key: {key[:10]}... (gesetzt)")
    else:
        print("Company Key: nicht gesetzt")


def main():
    parser = argparse.ArgumentParser(
        description="DeskAgent Config-Verschluesselung",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  # Neuen Key generieren
  python -m scripts.encryption --generate-key

  # Key auf diesem Rechner setzen
  python -m scripts.encryption --set-key DESK-xK9mP4qL7...

  # apis.json verschluesseln
  python -m scripts.encryption --encrypt config/apis.json

  # Alle Configs anzeigen
  python -m scripts.encryption --list
"""
    )

    parser.add_argument("--generate-key", action="store_true",
                        help="Generiert einen neuen Company Key")
    parser.add_argument("--set-key", metavar="KEY",
                        help="Speichert Company Key im Credential Manager")
    parser.add_argument("--get-key", action="store_true",
                        help="Zeigt gespeicherten Company Key")
    parser.add_argument("--encrypt", metavar="FILE",
                        help="Verschluesselt eine JSON-Datei")
    parser.add_argument("--decrypt", metavar="FILE",
                        help="Entschluesselt eine .enc Datei")
    parser.add_argument("--key", metavar="KEY",
                        help="Company Key fuer --encrypt/--decrypt")
    parser.add_argument("--list", action="store_true",
                        help="Listet Config-Dateien und Status")

    args = parser.parse_args()

    if args.generate_key:
        key = generate_key()
        print(f"\nNeuer Company Key:\n\n  {key}\n")
        print("Diesen Key sicher aufbewahren und an Mitarbeiter verteilen.")
        print("Zum Setzen auf diesem Rechner: --set-key " + key[:15] + "...")
        return

    if args.set_key:
        set_key(args.set_key)
        return

    if args.get_key:
        key = get_key()
        if key:
            print(f"Company Key: {key}")
        else:
            print("Kein Company Key gesetzt.")
        return

    if args.encrypt:
        path = Path(args.encrypt)
        if not path.exists():
            path = PROJECT_DIR / args.encrypt
        if not path.exists():
            print(f"[ERROR] Datei nicht gefunden: {args.encrypt}")
            return
        encrypt_file(path, company_key=args.key)
        return

    if args.decrypt:
        path = Path(args.decrypt)
        if not path.exists():
            path = PROJECT_DIR / args.decrypt
        if not path.exists():
            print(f"[ERROR] Datei nicht gefunden: {args.decrypt}")
            return
        decrypt_file(path, company_key=args.key)
        return

    if args.list:
        list_configs()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
