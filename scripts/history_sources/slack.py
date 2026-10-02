"""Collect Slack history through the user's connected slack-flujo MCP server."""
from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor, as_completed
from .common import timestamp, sanitize
from .mcp import Client, configured_endpoint


EXCLUDED_CHANNEL_NAMES = frozenset({'find-a-team', 'challenge-help', 'technical-help'})
_DM_TYPES = {'im', 'mpim', 'dm', 'group_dm', 'direct_message', 'group_direct_message'}


def _name(value):
    return str(value or '').strip().lstrip('#').strip().lower().replace('_', '-')


def _flag(value):
    return value is True or isinstance(value, str) and value.strip().lower() in {'true', 'yes', '1'}


def _channel_type(value):
    text = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')
    return {'public_channel': 'public_channel', 'private_channel': 'private_channel', 'direct_message': 'im',
            'dm': 'im', 'group_dm': 'mpim', 'group_direct_message': 'mpim'}.get(text, text)


def allowed_channel(channel, config=None):
    """One policy for live collection and previously captured Slack snapshots.

    Explicit DM signals always win over requested-channel configuration. Legacy
    D-channel/U-user IDs and DM names are rejected even when type flags were not
    captured; unknown G IDs cannot be read without a positive channel type.
    """
    config = config or {}
    identity = str(channel.get('id') or channel.get('channelId') or '')
    name = _name(channel.get('name') or channel.get('channel'))
    kind = _channel_type(channel.get('channelType') or channel.get('channel_type') or channel.get('conversation_type') or channel.get('type'))
    if _flag(channel.get('is_im')) or _flag(channel.get('is_mpim')) or kind in _DM_TYPES:
        return False
    if identity.upper().startswith(('D', 'U')) or channel.get('user'):
        return False
    if re.match(r'^(?:dm(?:\s+with|\s*:|$)|group[\s-]+dm\b|group[\s-]+direct[\s-]+message\b|direct[\s-]+message\b|mpdm-)', name, re.I):
        return False
    excluded = EXCLUDED_CHANNEL_NAMES | {_name(value) for value in config.get('slack_exclude_channels', [])}
    if name in excluded or _name(identity) in excluded:
        return False
    # Old Slack private channels and old MPIMs can both use G IDs. Without
    # explicit channel-type evidence, fail closed rather than export a group DM.
    if identity.upper().startswith('G') and not (kind in {'public_channel', 'private_channel'} or _flag(channel.get('is_channel'))):
        return False
    return bool(identity) and identity.upper().startswith(('C', 'G'))


def allowed_event(event, config=None):
    """Apply the same exclusions to old source/cache/browser history records."""
    if event.get('source') != 'slack':
        return True
    metadata = event.get('metadata', {})
    identity = metadata.get('channelId') or str(event.get('threadId') or '').split(':')[0]
    if not identity and str(event.get('id', '')).startswith('slack:'):
        identity = event['id'].split(':')[1]
    return allowed_channel({**metadata, 'id': identity, 'name': metadata.get('channel') or (event.get('tags') or [''])[0]}, config)


def _safe_slack_url(value):
    """Keep human Slack links without bearer query data or userinfo."""
    try:
        url = urlsplit(str(value or ''))
    except ValueError:
        return None
    host = (url.hostname or '').lower()
    if url.scheme != 'https' or url.username or url.password or not (host == 'slack.com' or host.endswith('.slack.com') or host == 'slack-edge.com' or host.endswith('.slack-edge.com')):
        return None
    # Query strings on private thumbnails can contain signed access tokens.
    # The official read_file tool is the authenticated byte-access mechanism.
    return urlunsplit((url.scheme, url.netloc, url.path, '', ''))


def _file_metadata(file):
    identity = str(file.get('id') or file.get('file_id') or '')
    if not re.fullmatch(r'F[A-Z0-9]+', identity):
        return None
    mime = str(file.get('mimetype') or file.get('mimeType') or '')
    result = {'id': identity, 'name': str(file.get('name') or file.get('title') or identity),
              'title': str(file.get('title') or file.get('name') or identity), 'mimeType': mime,
              'isImage': mime.lower().startswith('image/') and mime.lower() != 'image/svg+xml', 'readTool': 'slack_read_file'}
    if isinstance(file.get('size'), (int, float)):
        result['size'] = int(file['size'])
    for key in ('width', 'height', 'original_w', 'original_h'):
        if isinstance(file.get(key), (int, float)):
            result['width' if key in ('width', 'original_w') else 'height'] = int(file[key])
    permalink = _safe_slack_url(file.get('permalink'))
    if permalink and (urlsplit(permalink).hostname == 'files.slack.com' or '/files-pri/' in urlsplit(permalink).path):
        permalink = None
    if permalink:
        result['permalink'] = permalink
    if file.get('sizeBasis'):
        result['sizeBasis'] = file['sizeBasis']
    return sanitize(result)


def _message_media(message, body):
    reactions, files = [], []
    if isinstance(message.get('reactions'), list):
        for item in message['reactions']:
            if not isinstance(item, dict) or not item.get('name'):
                continue
            reaction = {'name': str(item['name']), 'count': int(item.get('count') or 0)}
            if isinstance(item.get('users'), list):
                reaction['users'] = [str(user) for user in item['users'] if isinstance(user, str)]
            reactions.append(reaction)
    else:
        for line in re.findall(r'(?m)^Reactions:\s*(.*)$', body):
            reactions.extend({'name': name.strip(':'), 'count': int(count)} for name, count in re.findall(r'([\w+:-]+)\s*\((\d+)\)', line))
    if isinstance(message.get('files'), list):
        files = [projection for file in message['files'] if isinstance(file, dict) and (projection := _file_metadata(file))]
    else:
        for line in re.findall(r'(?m)^Files?:\s*(.*)$', body):
            for match in re.finditer(r'(?:^|,\s*)(.*?)\s*\(ID:\s*(F[A-Z0-9]+),\s*([a-zA-Z0-9.+_-]+/[a-zA-Z0-9.+_-]+),\s*([\d.,]+)\s*(Bytes|B|KB|MB|GB)\)', line):
                name, identity, mime, count, unit = match.groups()
                size = int(float(count.replace(',', '')) * {'bytes': 1, 'b': 1, 'kb': 1024, 'mb': 1024**2, 'gb': 1024**3}[unit.lower()])
                file = _file_metadata({'id': identity, 'name': name, 'mimetype': mime, 'size': size, 'sizeBasis': 'Approximate, from connector formatted metadata'})
                if file:
                    files.append(file)
    return sanitize(reactions), files


def image_from_response(response):
    """Decode official read_file image content; no private HTTP URLs are fetched.

    Returns a raster byte payload for the caller's local/privacy-reviewed asset
    staging. SVG/HTML, inconsistent MIME bytes and oversized content are denied.
    The response itself is untrusted user content and is never executed.
    """
    candidates = response.get('content', []) if isinstance(response, dict) else []
    if isinstance(response, dict) and isinstance(response.get('structuredContent'), dict):
        candidates = [*candidates, response['structuredContent']]
    if isinstance(response, dict) and response.get('mimeType'):
        candidates = [*candidates, response]
    for part in candidates:
        if not isinstance(part, dict):
            continue
        mime = str(part.get('mimeType') or part.get('mimetype') or '').lower()
        encoded = part.get('data') or part.get('base64')
        if mime not in {'image/png', 'image/jpeg', 'image/gif', 'image/webp'} or not isinstance(encoded, str) or len(encoded) > 14_000_000:
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            continue
        valid = (mime == 'image/png' and data.startswith(b'\x89PNG\r\n\x1a\n') or mime == 'image/jpeg' and data.startswith(b'\xff\xd8\xff')
                 or mime == 'image/gif' and data[:6] in (b'GIF87a', b'GIF89a') or mime == 'image/webp' and data[:4] == b'RIFF' and data[8:12] == b'WEBP')
        if valid and len(data) <= 10 * 1024 * 1024:
            return {'data': data, 'mimeType': mime, 'extension': {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp'}[mime]}
    return None


def next_cursor(response):
    meta = response.get("response_metadata", {})
    if meta.get("next_cursor") or response.get("next_cursor"):
        return meta.get("next_cursor") or response["next_cursor"]
    text = str(response.get("pagination_info", "")) + "\n" + (response.get("result", "") if isinstance(response.get("result"), str) else "")
    match = re.search(r"(?:next_cursor|cursor)\s*(?:[:=]|is)\s*[`\"']?([A-Za-z0-9+/=_-]+)", text, re.I)
    return match.group(1) if match else None


def channels_from(response):
    if isinstance(response.get("channels"), list):
        result = []
        for channel in response['channels']:
            if not isinstance(channel, dict) or not channel.get('id'):
                continue
            kind = _channel_type(channel.get('channelType') or channel.get('type') or channel.get('channel_type'))
            if not kind:
                kind = 'mpim' if _flag(channel.get('is_mpim')) else 'im' if _flag(channel.get('is_im')) else 'private_channel' if _flag(channel.get('is_private')) else 'public_channel' if _flag(channel.get('is_channel')) else ''
            result.append({'id': channel['id'], 'name': channel.get('name') or channel.get('user') or channel['id'], 'user': channel.get('user'),
                           'channelType': kind, **{key: _flag(channel[key]) for key in ('is_im', 'is_mpim', 'is_channel', 'is_group', 'is_private', 'is_archived') if key in channel}})
        return result
    text = response.get("result", "")
    channels = []
    for block in re.split(r"\n### ", text)[1:]:
        match = re.search(r"\*\*ID:\*\*\s*(\w+)", block)
        user = re.search(r"\*\*User ID:\*\*\s*(\w+)", block)
        kind = re.search(r"\*\*Type:\*\*\s*([^\n]+)", block)
        if match:
            channel_type = _channel_type(kind[1]) if kind else ''
            name = block.splitlines()[0].lstrip('#').strip()
            dm = match[1].startswith('D') or bool(user) or channel_type == 'im' or bool(re.match(r'^DM\b', name, re.I))
            mpim = channel_type == 'mpim' or bool(re.match(r'^(?:Group DM|mpdm-)', name, re.I))
            channels.append({'id': match[1], 'name': name, 'user': user[1] if user else None, 'channelType': 'mpim' if mpim else 'im' if dm else channel_type,
                             'is_im': dm and not mpim, 'is_mpim': mpim})
    return channels


def messages_from(response, channel, parent=None):
    value = response.get("messages", "")
    if isinstance(value, list):
        result = []
        for message in value:
            if not isinstance(message, dict) or not message.get('ts'):
                continue
            body = str(message.get('text') or '')
            reactions, files = _message_media(message, body)
            result.append({'ts': message['ts'], 'body': body, 'actor': message.get('user') or message.get('bot_id') or 'Slack',
                           'replies': message.get('reply_count', 0), 'parent': message.get('thread_ts') or parent,
                           'reactions': reactions, 'files': files, '_mediaProvided': [key for key in ('reactions', 'files') if key in message]})
        return result
    records = []
    # The connected server exposes human-readable messages. Preserve the entire
    # body plus reactions/files; TS is authoritative, display date is ancillary.
    headers = list(re.finditer(r"(?m)^=== Message from (.*?) at (.*?) ===\s*\nMessage TS: (\d+\.\d+)\n", value))
    if headers:
        for i, head in enumerate(headers):
            body = value[head.end():headers[i + 1].start() if i + 1 < len(headers) else len(value)].strip()
            replies = re.search(r"(?m)^Thread: (\d+) replies", body)
            reactions, files = _message_media({}, body)
            records.append({"ts": head[3], "body": body, "actor": re.sub(r" <[^>]+>", "", head[1]), "replies": int(replies[1]) if replies else 0, "parent": parent, 'reactions': reactions, 'files': files, '_mediaProvided': [key for key, pattern in [('reactions', r'(?m)^Reactions:'), ('files', r'(?m)^Files?:')] if re.search(pattern, body)]})
    else:
        heads = list(re.finditer(r"(?m)^From: (.*?)\nTime: .*?\nMessage TS: (\d+\.\d+)\n", value))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(value)
            body = value[head.end():end]
            body = re.sub(r"(?m)^(?:=== THREAD REPLIES.*?===|--- Reply \d+ of \d+ ---)\s*", "", body).strip()
            reactions, files = _message_media({}, body)
            records.append({"ts": head[2], "body": body, "actor": re.sub(r" <[^>]+>", "", head[1]), "replies": 0, "parent": parent, 'reactions': reactions, 'files': files, '_mediaProvided': [key for key, pattern in [('reactions', r'(?m)^Reactions:'), ('files', r'(?m)^Files?:')] if re.search(pattern, body)]})
    return records


def collect(repo, config):
    events, notes, channels, failures = {}, [], [], []
    try:
        url, headers = configured_endpoint(config)
        client = Client(url, headers)
        cursor, cursors = None, set()
        while True:
            args = {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": False}
            if cursor:
                args["cursor"] = cursor
            response = client.call("slack_list_user_channels", args)
            channels.extend(channels_from(response))
            new = next_cursor(response)
            if not new:
                break
            if new in cursors:
                raise RuntimeError("Channel listing repeated its pagination cursor")
            cursors.add(new)
            cursor = new
        channels = list({c["id"]: c for c in channels}.values())
        excluded_count = sum(not allowed_channel(channel, config) for channel in channels)
        channels = [channel for channel in channels if allowed_channel(channel, config)]
        if config.get("slack_channels"):
            requested = set(config["slack_channels"])
            channels = [c for c in channels if c["id"] in requested or c["name"] in requested]
        if not channels:
            return {'events': [], 'status': 'ok', 'notes': ['No permitted Slack channels selected. Direct messages, group DMs, find-a-team, challenge-help and technical-help are excluded before reads.'], 'channels': [], 'stats': {'channels': 0, 'excludedChannels': excluded_count, 'messages': 0, 'threads': 0}}

        def read_conversation(channel):
            result, errors, cursor, cursors = {}, [], None, set()

            def keep_records(records):
                for message in records:
                    prior = result.get(message['ts'], {})
                    # Thread responses can omit parent media fields. An absent
                    # field cannot erase metadata returned by channel history;
                    # an explicit empty list remains an authoritative snapshot.
                    for key in ('reactions', 'files'):
                        if key not in message.get('_mediaProvided', []) and prior.get(key):
                            message[key] = prior[key]
                    result[message['ts']] = message
            while True:
                args = {"channel_id": channel["id"], "limit": 100, "response_format": "detailed"}
                if cursor:
                    args["cursor"] = cursor
                response = client.call("slack_read_channel", args)
                records = messages_from(response, channel)
                if not records and re.search(r"error|not_found|not_in_channel|missing_scope", str(response), re.I):
                    raise RuntimeError("Slack history inaccessible")
                keep_records(records)
                new = next_cursor(response)
                if not new:
                    info = str(response.get("pagination_info", ""))
                    if re.search(r"more (?:messages|pages|results) (?:are )?available", info, re.I) and not re.search(r"no more", info, re.I):
                        errors.append("Unrecognized history pagination")
                    break
                if new in cursors:
                    errors.append("Repeated history cursor")
                    break
                cursors.add(new)
                cursor = new
            thread_count = 0
            for message in list(result.values()):
                if message["replies"]:
                    cursor, cursors = None, set()
                    reply_timestamps = set()
                    try:
                        while True:
                            args = {"channel_id": channel["id"], "message_ts": message["ts"], "limit": 1000, "response_format": "detailed"}
                            if cursor:
                                args["cursor"] = cursor
                            response = client.call("slack_read_thread", args)
                            replies = messages_from(response, channel, message["ts"])
                            reply_timestamps.update(m["ts"] for m in replies)
                            keep_records(replies)
                            new = next_cursor(response)
                            if not new:
                                if len(reply_timestamps) < message["replies"] + 1:
                                    errors.append(f"Thread {message['ts']} returned fewer replies than the channel reported")
                                break
                            if new in cursors:
                                errors.append(f"Thread {message['ts']} repeated cursor")
                                break
                            cursors.add(new)
                            cursor = new
                        thread_count += 1
                    except Exception as error:
                        errors.append(f"Thread {message['ts']}: {type(error).__name__}")
            rows = []
            for m in result.values():
                ts = m["ts"]
                files = m.get('files', [])
                rows.append({"id": f"slack:{channel['id']}:{ts}", "timestamp": timestamp(ts), "source": "slack", "kind": "reply" if m.get("parent") and m["parent"] != ts else "message", "title": m["body"].splitlines()[0][:180] if m["body"] else "Shared a file", "body": m["body"], "actor": m["actor"], "url": f"https://factored-hackathon.slack.com/archives/{channel['id']}/p{ts.replace('.', '')}", "threadId": f"{channel['id']}:{m.get('parent') or ts}", "tags": [channel["name"]], "metadata": {"channelId": channel["id"], "channel": channel["name"], 'channelType': channel.get('channelType'), 'is_im': False, 'is_mpim': False, "messageTs": ts, "threadTs": m.get("parent"), "replyCount": m["replies"], 'reactions': m.get('reactions', []), 'reactionTimestampBasis': 'Snapshot at message capture; reaction creation times unavailable', 'files': files, 'images': [file for file in files if file.get('isImage')]}})
            return rows, errors, thread_count

        counts, thread_count = [], 0
        with ThreadPoolExecutor(max_workers=config.get("slack_workers", 3)) as pool:
            pending = {pool.submit(read_conversation, channel): channel for channel in channels}
            for task in as_completed(pending):
                channel = pending[task]
                try:
                    rows, errors, threads = task.result()
                    events.update({e["id"]: e for e in rows})
                    counts.append({**channel, "messages": len(rows), "threads": threads, "errors": errors})
                    thread_count += threads
                    failures.extend(f"{channel['name']}: {error}" for error in errors)
                    print(f"  Slack {channel['name']}: {len(rows)} messages, {threads} threads", flush=True)
                except Exception as error:
                    failures.append(f"{channel['name']}: {type(error).__name__}: {str(error)[:120]}")
        notes.append('Read through connected slack-flujo MCP: permitted public/private channels, archived channel history and complete thread replies. All direct messages/group DMs and find-a-team/challenge-help/technical-help are excluded before content reads. Deleted Slack text cannot be recovered.')
        notes.append('Reactions are capture snapshots, without invented creation timestamps. Files/images retain safe metadata. Image bytes can be read only through official slack_read_file(file_id); no private URL tokens or provider credentials are exported.')
        return sanitize({"events": list(events.values()), "status": "partial" if failures else "ok", "notes": notes + failures, "stats": {"channels": len(channels), 'excludedChannels': excluded_count, "readableChannels": len(counts), "threads": thread_count, "messages": len(events), 'imageMessages': sum(bool(e['metadata']['images']) for e in events.values()), 'reactionMessages': sum(bool(e['metadata']['reactions']) for e in events.values())}, "channels": counts})
    except Exception as error:
        return {"events": list(events.values()), "status": "partial" if events else "unavailable", "notes": [f"Slack MCP: {type(error).__name__}: {str(error)[:200]}"]}
