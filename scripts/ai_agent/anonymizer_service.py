# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Anonymizer Service - Standalone service for PII anonymization.

This service runs in the embedded Python and handles spacy/presidio imports
that cannot be compiled with Nuitka.

Usage:
    # One-shot mode (subprocess):
    echo "Max Mustermann" | python -m anonymizer_service --anonymize --lang de

    # Daemon mode (HTTP server):
    python -m anonymizer_service --daemon --port 8766

    # Check if models are installed:
    python -m anonymizer_service --check-models
"""

import sys
import json
import argparse
from typing import Optional, Tuple, Dict, Any

# Lazy load heavy imports
_analyzer = None
_anonymizer = None
_models_checked = False


def _log(msg: str):
    """Log to stderr (stdout is reserved for output)."""
    print(f"[AnonymizerService] {msg}", file=sys.stderr)


def check_models() -> dict:
    """Check which spacy models are available."""
    result = {"available": [], "missing": [], "spacy_installed": False}

    try:
        import spacy
        result["spacy_installed"] = True

        required_models = [
            ("de_core_news_lg", "de_core_news_md", "de_core_news_sm"),
            ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"),  # sm bundled in installer
        ]

        for model_options in required_models:
            found = False
            for model in model_options:
                if spacy.util.is_package(model):
                    result["available"].append(model)
                    found = True
                    break
            if not found:
                result["missing"].append(model_options[0])  # Report preferred model

    except ImportError:
        result["spacy_installed"] = False
        result["missing"] = ["de_core_news_lg", "en_core_web_sm"]

    return result


def _get_analyzer(language: str = "de"):
    """Get or create Presidio analyzer (lazy initialization)."""
    global _analyzer

    if _analyzer is not None:
        return _analyzer

    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        import spacy

        # Build models list based on available models
        models_list = []

        # German models (prefer large)
        for model in ["de_core_news_lg", "de_core_news_md", "de_core_news_sm"]:
            if spacy.util.is_package(model):
                models_list.append({"lang_code": "de", "model_name": model})
                break

        # English models (prefer sm, bundled in installer)
        for model in ["en_core_web_sm", "en_core_web_md", "en_core_web_lg"]:
            if spacy.util.is_package(model):
                models_list.append({"lang_code": "en", "model_name": model})
                break

        if models_list:
            configuration = {
                "nlp_engine_name": "spacy",
                "models": models_list,
                "ner_model_configuration": {
                    "labels_to_ignore": ["MISC"]
                }
            }
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()

            supported_languages = [m["lang_code"] for m in models_list]
            _analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine,
                supported_languages=supported_languages
            )
            _log(f"Initialized with models: {[m['model_name'] for m in models_list]}")
        else:
            _analyzer = AnalyzerEngine()
            _log("Using default analyzer (no spacy models found)")

    except Exception as e:
        _log(f"Error initializing analyzer: {e}")
        raise

    return _analyzer


def _get_anonymizer():
    """Get or create Presidio anonymizer."""
    global _anonymizer

    if _anonymizer is None:
        from presidio_anonymizer import AnonymizerEngine
        _anonymizer = AnonymizerEngine()

    return _anonymizer


def anonymize(
    text: str,
    language: str = "de",
    pii_types: list = None,
    placeholder_format: str = "<{entity_type}_{index}>",
    confidence_threshold: float = 0.75
) -> Tuple[str, Dict[str, str]]:
    """
    Anonymize PII in text.

    Args:
        text: Input text with PII
        language: Language code (de, en)
        pii_types: List of PII types to detect
        placeholder_format: Format for placeholders

    Returns:
        Tuple of (anonymized_text, mappings dict)
    """
    if not text or not text.strip():
        return text, {}

    if pii_types is None:
        pii_types = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION"]

    try:
        analyzer = _get_analyzer(language)
        anonymizer = _get_anonymizer()

        # Analyze text
        results = analyzer.analyze(
            text=text,
            entities=pii_types,
            language=language
        )

        if not results:
            return text, {}

        # Build mappings and anonymize
        mappings = {}
        counters = {}
        anonymized = text

        # Sort by position (descending) for safe replacement
        results = sorted(results, key=lambda x: x.start, reverse=True)

        for result in results:
            original = text[result.start:result.end]
            entity_type = result.entity_type

            # Skip low confidence or short matches
            if result.score < confidence_threshold or len(original) < 3:
                continue

            # Generate placeholder
            counter = counters.get(entity_type, 0) + 1
            counters[entity_type] = counter
            placeholder = placeholder_format.format(
                entity_type=entity_type,
                index=counter
            )

            mappings[placeholder] = original
            anonymized = anonymized[:result.start] + placeholder + anonymized[result.end:]

        return anonymized, mappings

    except Exception as e:
        _log(f"Error during anonymization: {e}")
        return text, {}


def deanonymize(text: str, mappings: Dict[str, str]) -> str:
    """Restore original PII values."""
    result = text
    for placeholder, original in mappings.items():
        result = result.replace(placeholder, original)
    return result


def run_daemon(port: int = 8766):
    """Run as HTTP daemon for low-latency requests."""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import json

        class AnonymizerHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                _log(f"HTTP: {format % args}")

            def do_POST(self):
                if self.path == "/anonymize":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")

                    try:
                        data = json.loads(body)
                        text = data.get("text", "")
                        lang = data.get("lang", "de")
                        pii_types = data.get("pii_types")
                        confidence_threshold = data.get("confidence_threshold", 0.75)

                        anonymized, mappings = anonymize(text, lang, pii_types, confidence_threshold=confidence_threshold)

                        response = json.dumps({
                            "anonymized": anonymized,
                            "mappings": mappings
                        })

                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(response.encode("utf-8"))

                    except Exception as e:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

                elif self.path == "/deanonymize":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")

                    try:
                        data = json.loads(body)
                        text = data.get("text", "")
                        mappings = data.get("mappings", {})

                        result = deanonymize(text, mappings)

                        response = json.dumps({"text": result})
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(response.encode("utf-8"))

                    except Exception as e:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

                elif self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')

                else:
                    self.send_response(404)
                    self.end_headers()

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                else:
                    self.send_response(404)
                    self.end_headers()

        # Pre-load models
        _log("Pre-loading spacy models...")
        _get_analyzer("de")
        _log("Models loaded, starting HTTP server...")

        server = HTTPServer(("127.0.0.1", port), AnonymizerHandler)
        _log(f"Anonymizer daemon running on http://127.0.0.1:{port}")
        server.serve_forever()

    except Exception as e:
        _log(f"Daemon error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Anonymizer Service")
    parser.add_argument("--anonymize", action="store_true", help="Anonymize stdin input")
    parser.add_argument("--deanonymize", action="store_true", help="Deanonymize with mappings")
    parser.add_argument("--lang", default="de", help="Language (de, en)")
    parser.add_argument("--daemon", action="store_true", help="Run as HTTP daemon")
    parser.add_argument("--port", type=int, default=8766, help="Daemon port")
    parser.add_argument("--check-models", action="store_true", help="Check available models")
    parser.add_argument("--json", action="store_true", help="JSON input/output mode")

    args = parser.parse_args()

    if args.check_models:
        result = check_models()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["available"] else 1)

    if args.daemon:
        run_daemon(args.port)
        return

    if args.anonymize:
        if args.json:
            # JSON mode: read JSON object with text and options
            input_data = json.loads(sys.stdin.read())
            text = input_data.get("text", "")
            lang = input_data.get("lang", args.lang)
            pii_types = input_data.get("pii_types")
            placeholder_format = input_data.get("placeholder_format", "<{entity_type}_{index}>")
            confidence_threshold = input_data.get("confidence_threshold", 0.75)

            anonymized, mappings = anonymize(text, lang, pii_types, placeholder_format, confidence_threshold)
            print(json.dumps({"anonymized": anonymized, "mappings": mappings}))
        else:
            # Simple mode: read text, output anonymized text
            text = sys.stdin.read()
            anonymized, mappings = anonymize(text, args.lang)
            print(anonymized)
            # Mappings go to stderr in simple mode
            if mappings:
                print(json.dumps(mappings), file=sys.stderr)

    elif args.deanonymize:
        input_data = json.loads(sys.stdin.read())
        text = input_data.get("text", "")
        mappings = input_data.get("mappings", {})
        result = deanonymize(text, mappings)
        print(result)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
