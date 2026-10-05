"""Shared timestamps and privacy filtering for exported development history.

Personal contacts are masked in text, nested records, and URL parameters.
Technical identifiers and unlabelled numbers are not treated as personal IDs.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import unquote


def timestamp(value):
    if isinstance(value, (float, int)) or (isinstance(value, str) and re.fullmatch(r"\d+(\.\d+)?", value)):
        number = float(value)
        if number > 1e11:
            number /= 1000
        return datetime.fromtimestamp(number, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return date.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_id(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:20]


def content_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(content_text(item) for item in value)
    if isinstance(value, dict):
        if value.get("type") in ("thinking", "reasoning", "analysis"):
            return ""
        for key in ("text", "content", "output", "result"):
            if key in value:
                return content_text(value[key])
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


_PATTERNS = [
    (r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z ]+)?PRIVATE KEY-----", "[REDACTED PRIVATE KEY]"),
    (r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{15,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b", "[REDACTED TOKEN]"),
    (r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]{16,}=*", r"\1[REDACTED]"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "[REDACTED JWT]"),
    (r"(?im)((?:AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|(?:[A-Z_]*)(?:API_KEY|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD|CLIENT_SECRET))\s*[=:]\s*[\"']?)([^\s\"'`,;}{]{8,})", r"\1[REDACTED]"),
    (r"(?i)([\"'](?:apiKey|accessToken|secretAccessKey|clientSecret|password|authorization)[\"']\s*:\s*[\"'])([^\"']{8,})([\"'])", r"\1[REDACTED]\3"),
    (r"(?i)([\"'](?:[a-z0-9_]*_)?(?:api_key|access_token|refresh_token|auth_token|secret_access_key|secret_key|client_secret|password|token)[\"']\s*:\s*[\"'])([^\"']{8,})([\"'])", r"\1[REDACTED]\3"),
    (r"(?i)([?&](?:token|key|api_key|access_token|auth|password)=)[^&\s\"'<>]+", r"\1[REDACTED]"),
    (r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@"),
]

_EMAIL = re.compile(r"(?<![\w.!#$%&'*+^`{}~-])[\w.!#$%&'*+^`{}~-]+(?:@|%40|%2540|&#64;|&#x40;|&commat;)(?:[\w%-]+(?:\.|%2e|%252e|&#46;|&#x2e;))+[\w%-]{2,63}(?![\w-])", re.I)
_INTERNATIONAL_PHONE = re.compile(r"(?<![\w.])(?:\(\s*)?\+\s*\d{1,3}\s*\)?(?:[ ()\u00a0.-]*\d){6,14}(?:\s*(?:ext\.?|extension|x)\s*\d{1,6})?(?![\w\d]|\.\d)", re.I)
_GROUPED_PHONE = re.compile(r"(?<![\w.+-])(?:\([2-9]\d{2}\)|[2-9]\d{2})[ \u00a0.-]+\d{3}[ \u00a0.-]+\d{4}(?:\s*(?:ext\.?|extension|x)\s*\d{1,6})?(?![\w\d-]|\.\d)", re.I)
_BARE_PHONE = re.compile(r"(?<![\w.+-])(?:[2-9]\d{2}[ \u00a0-]+\d{7}|\d{7,15}|\d{3}-\d{4})(?![\w\d-]|\.\d)")
_PHONE_CONTEXT = re.compile(r"(?:\b(?:phone|telephone|tel[eé]fono|tel|mobile|cellphone|celular|whatsapp|sms|call|ll[aá]ma(?:me)?|contact(?:o)?(?:\s+(?:number|me))?)\b|\breach\s+me\s+at\b)[^\n\r]{0,45}$", re.I)
_TECHNICAL_CONTEXT = re.compile(r"\b(?:version|release|build|semver|sha|hash|timestamp|epoch|float|decimal|precision|port|pid|counter|serial|commit|id|(?:call|thread|event|session|machine|message)[_ ]id)\b[\"']?\s*[:=#]?\s*[\"']?(?:v)?$", re.I)
_LABELLED_VALUE = re.compile(r"(?P<key>[\"']?[A-Za-z\u00c0-\u024f][A-Za-z0-9_\u00c0-\u024f.-]{0,70}[\"']?)\s*(?P<separator>[:=])\s*(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^,;\n\r}&]+)")
_CONTACT_QUERY = re.compile(r"(?P<prefix>[?&](?P<key>[A-Za-z0-9_%.-]{1,70})=)(?P<value>[^&#\s\"'<>]*)")
_PHONE_URI = re.compile(r"(?P<prefix>\b(?:tel|sms):|https?://(?:www\.)?wa\.me/)(?P<value>(?:\+|%2b|%252b)?[0-9%() .-]{7,80})(?:;ext=\d{1,6})?", re.I)
_PERSONAL_ID_IN_PROSE = re.compile(r"(?P<prefix>\b(?:c[eé]dula(?:\s+(?:de\s+ciudadan[ií]a|n[uú]mero))?|dni|ssn|social\s+security(?:\s+number)?|passport(?:\s+number)?|national\s+id)(?:\s+(?:es|is|n[uú]mero|number))?\s*[:=#]?\s+)(?P<value>[A-Z]{0,3}\d(?:[\d .-]{3,20}\d))(?!\w)", re.I)
_TECHNICAL_KEYS = {
    "id", "ids", "eventid", "eventids", "threadid", "threadids", "parentthreadid", "forkedfromid", "sessionid", "sessionids",
    "callid", "callids", "conversationid", "conversationids", "messageid", "messageids", "flowid", "workspaceid", "machineid", "machineids",
    "buildid", "deploymentid", "sha", "headsha", "treesha", "commitsha", "timestamp", "rawtimestamp", "createdat", "updatedat", "startedat", "finishedat",
    "generatedat", "observedat", "collectedat", "cachedat", "evidenceeventids", "evidencesourceeventids", "fromeventid", "toeventid",
}
_EMAIL_KEYS = {"email", "emails", "emailaddress", "emailaddresses", "emailfrom", "emailto", "contactemail", "correo", "correoelectronico"}
_PHONE_KEYS = {"phone", "phones", "phonenumber", "phonenumbers", "telephone", "telephonenumber", "tel", "telefono", "telefonos", "mobile", "mobilenumber", "cell", "cellphone", "cellnumber", "whatsapp", "contactnumber", "celular"}
_ADDRESS_KEYS = {"homeaddress", "streetaddress", "residentialaddress", "postaladdress", "mailingaddress", "billingaddress", "shippingaddress", "customeraddress", "physicaladdress", "direccion", "direccionpostal", "domicilio", "addressline1", "addressline2", "streetline1", "streetline2"}
_PERSONAL_ID_KEYS = {"nationalid", "nationalidnumber", "nationalidentificationnumber", "cedula", "cedulaciudadania", "dni", "ssn", "socialsecuritynumber", "passport", "passportnumber", "identificationnumber", "documentnumber", "personalid", "taxpayerid", "taxid", "nit", "rut", "accountnumber", "bankaccountnumber", "cardnumber", "creditcardnumber", "debitcardnumber", "iban", "cbu"}
_ADDRESS_SHAPE = re.compile(r"\b(?:calle|carrera|avenida|av\.?|street|st\.?|road|rd\.?|boulevard|blvd\.?|apartment|apt\.?|suite|piso|barrio|postal|zip)\b", re.I)
_SYMBOLIC_VALUE = re.compile(r"^(?:\$[\w{]|process\.|os\.environ|(?:None|null|undefined|true|false|string|number|boolean|str|int|float|Optional|Dict|List)\b|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$)")
_MARKERS = {"email": "[REDACTED EMAIL]", "phone": "[REDACTED PHONE]", "address": "[REDACTED ADDRESS]", "personal_id": "[REDACTED PERSONAL ID]", "contact": "[REDACTED CONTACT]"}


def _key(value):
    value = unicodedata.normalize("NFKD", str(value))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _personal_kind(key):
    key = _key(key)
    if key in _TECHNICAL_KEYS:
        return None
    if key in _EMAIL_KEYS or key.endswith(("email", "emailaddress", "emailaddresses")):
        return "email"
    if key in _PHONE_KEYS or key.endswith(("phone", "phonenumber", "telephonenumber", "mobilenumber", "contactnumber")):
        return "phone"
    if key in _ADDRESS_KEYS or key.endswith(("homeaddress", "streetaddress", "residentialaddress", "postaladdress", "mailingaddress", "billingaddress", "shippingaddress")):
        return "address"
    if key in _PERSONAL_ID_KEYS:
        return "personal_id"
    if key in {"contact", "contactdetails", "contactinfo", "contactinformation"}:
        return "contact"
    return None


def _human_address(value):
    if isinstance(value, dict):
        return any(_key(key) in {"street", "streetaddress", "addressline1", "postalcode", "zipcode", "city", "apartment"} for key in value)
    if not isinstance(value, str):
        return False
    return bool(_ADDRESS_SHAPE.search(value)) and not bool(re.match(r"(?:https?://|[A-Za-z]:[/\\]|/(?:tmp|data|app|home)/)", value))


def _mask_shape(value, marker):
    """Keep nested contact structure, replacing values rather than its keys."""
    if isinstance(value, dict):
        return {key: _mask_shape(item, marker) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_shape(item, marker) for item in value]
    if value is None or isinstance(value, bool):
        return value
    return marker


def _redact_personal_text(value):
    # Explicit query-field names establish meaning even for fully URL-encoded
    # values. Keep URL delimiters and unrelated technical parameters intact.
    def query(match):
        kind = _personal_kind(unquote(unquote(match["key"])))
        if not kind or not match["value"]:
            return match[0]
        return match["prefix"] + "%5BREDACTED_" + kind.upper() + "%5D"
    value = _CONTACT_QUERY.sub(query, value)
    value = _PHONE_URI.sub(lambda match: match["prefix"] + "%5BREDACTED_PHONE%5D" if 7 <= len(re.sub(r"\D", "", unquote(unquote(match["value"])))) <= 15 else match[0], value)

    def email(match):
        # git@host:path is an SSH remote, not a human email address.
        suffix = value[match.end():match.end()+120]
        if match[0].lower().startswith("git@") and re.match(r":[^\s]+(?:\.git)?", suffix):
            return match[0]
        return _MARKERS["email"]
    value = _EMAIL.sub(email, value)

    def labelled(match):
        kind = _personal_kind(match["key"].strip("\"'"))
        raw = match["value"].strip()
        if not kind and _key(match["key"]) == "address" and _human_address(raw):
            kind = "address"
        if not kind or kind == "contact" or not raw:
            return match[0]
        quote = raw[0] if raw[0] in "\"'" and raw[-1:] == raw[0] else ""
        inside = raw[1:-1] if quote else raw
        if not quote and _SYMBOLIC_VALUE.match(inside) and not (kind == "personal_id" and len(re.sub(r"\D", "", inside)) >= 5):
            return match[0]
        if inside.upper().startswith(("[REDACTED ", "%5BREDACTED_")):
            return match[0]
        # Quoted markers remain quoted; bare JSON/Python numeric values become
        # string markers, keeping the surrounding program/record parseable.
        replacement = (quote or '"') + _MARKERS[kind] + (quote or '"')
        start = match.start("value") - match.start()
        return match[0][:start] + replacement
    value = _LABELLED_VALUE.sub(labelled, value)
    value = _PERSONAL_ID_IN_PROSE.sub(lambda match: match["prefix"] + _MARKERS["personal_id"], value)

    def phone(match):
        prefix = value[max(0, match.start()-75):match.start()]
        if _TECHNICAL_CONTEXT.search(prefix):
            return match[0]
        # Reject arbitrary positive long integers and impossible E.164 lengths.
        number = re.split(r"(?:ext\.?|extension|x)", match[0], flags=re.I)[0]
        if not 7 <= len(re.sub(r"\D", "", number)) <= 15:
            return match[0]
        return _MARKERS["phone"]
    value = _INTERNATIONAL_PHONE.sub(phone, value)
    value = _GROUPED_PHONE.sub(phone, value)
    value = _BARE_PHONE.sub(lambda match: phone(match) if _PHONE_CONTEXT.search(value[max(0, match.start()-75):match.start()]) else match[0], value)
    return value


def redact(value):
    value = str(value)
    for pattern, replacement in _PATTERNS:
        value = re.sub(pattern, replacement, value)
    # FLUJO/GitHub tool traces frequently contain JSON inside JSON strings.
    # Recursing through parsed records masks a bare numeric phone field while
    # keeping both outer and embedded records parseable, and protects IDs.
    stripped = value.strip()
    if stripped[:1] in {"{", "["} and stripped[-1:] in {"}", "]"}:
        try:
            decoded = json.loads(value)
            if isinstance(decoded, (dict, list)):
                safe = sanitize(decoded)
                if safe == decoded:
                    return value
                return json.dumps(safe, ensure_ascii=False, indent=2 if "\n" in value else None)
        except (ValueError, TypeError, RecursionError):
            pass
    return _redact_personal_text(value)


def contains_private_data(value):
    """Shared contact/credential detector for local artifact/OCR screening."""
    return redact(value) != str(value)


def sanitize(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        secret_keys = {"api_key", "apikey", "access_token", "accesstoken", "refresh_token", "auth_token", "authorization", "aws_secret_access_key", "secret_access_key", "secretaccesskey", "client_secret", "clientsecret", "password"}
        result = {}
        for key, item in value.items():
            normalized = _key(key)
            kind = _personal_kind(key)
            if str(key).lower() in secret_keys and isinstance(item, str):
                result[key] = "[REDACTED]"
            elif normalized in _TECHNICAL_KEYS and (isinstance(item, (str, int, float)) or item is None or isinstance(item, list) and all(isinstance(child, (str, int, float)) or child is None for child in item)):
                # Stable identity arrays / timestamps are required to connect
                # evidence and must not be rewritten by heuristic phone rules.
                result[key] = item
            elif kind and not isinstance(item, bool) and item is not None:
                schema_types = {"string", "number", "integer", "boolean", "array", "object", "null"}
                field_type = item.get("type") if isinstance(item, dict) else None
                is_schema = isinstance(field_type, str) and field_type in schema_types or isinstance(field_type, list) and bool(field_type) and all(isinstance(part, str) and part in schema_types for part in field_type)
                if is_schema or kind == "contact" and isinstance(item, (dict, list)):
                    result[key] = sanitize(item)
                else:
                    result[key] = _mask_shape(item, _MARKERS[kind])
            elif normalized == "address" and _human_address(item):
                result[key] = _mask_shape(item, _MARKERS["address"])
            else:
                result[key] = sanitize(item)
        return result
    return value
