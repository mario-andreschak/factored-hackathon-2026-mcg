"""Allowlisted, local-only public evidence bundle; never performs network/provider work."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import argparse, base64, hashlib, json, re, sys, wave

TMP = Path('C:/Users/Moe/.codex/tmp')
CONTEXT = TMP / 'savia-ui-runtime-c44d416fcf1a'
HELPERS = TMP / 'savia-ack-successor-qualification'
BUILD = TMP / 'savia-ui-successor-helper'
OUT = TMP / 'savia-ack-successor-public-prepared'
HEAD = 'c44d416fcf1ab95bcb16c77651418e6570d79782'
TREE = 'fabf02d622f51302e229137405e3607356d00ab0'
IMAGE = 'registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c'
DESCRIPTOR = '3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9'
PORTAL = '634aa5244374b3e105ef7864fa100530bab45ec2'
NATIVE = '6219bc81a8a4c7f2936769e7727e5146dd2713d0'
EXTERNAL = Path('C:/Users/Moe/.codex/worktrees/savia-review-evidence/factored-hackathon-2026/.tmp/portal-external-destinations-634aa524.json')
PRIVATE_BASE = TMP / 'savia-ack-successor-native-private-c44d416fcf1a'
PT_PRIVATE_BASE = TMP / 'savia-ack-pt-continuation-native-private-c44d416fcf1a'
PT_HELPERS = TMP / 'savia-ack-pt-continuation-helper'
PARTIAL_SHA = '67c436c315c0bb729ff5c68bc3d6919cea9eb5c5076d5a410f044e4960bd5c9e'

def require(ok, message):
    if not ok: raise RuntimeError(message)

def sha(data): return hashlib.sha256(data).hexdigest()
def raw(file):
    file = Path(file)
    require(file.is_file() and not file.is_symlink(), 'Regular source file required: ' + str(file))
    return file.read_bytes()
def load(file): return json.loads(raw(file))
def json_bytes(value): return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')

def destination(name):
    p = PurePosixPath(name)
    require(p.as_posix() == name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name,
            'Unsafe bundle-relative path')
    target = OUT / name
    require(OUT.resolve() in target.resolve().parents, 'Destination escaped public bundle')
    require(not target.is_symlink(), 'Bundle symlink denied')
    return target

def put(name, data):
    target = destination(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        require(raw(target) == data, 'Existing public artifact differs; never overwrite: ' + name)
    else:
        with target.open('xb') as stream: stream.write(data)

def mapping_copy(name, file, mappings, classification='public byte-identical source/metadata'):
    data = raw(file)
    put(name, data)
    mappings[name] = {'original_path':str(file),'original_sha256':sha(data),
        'public_sha256':sha(data),'bytes':len(data),'conversion':'byte-identical','classification':classification}

def derivative(name, value, source, mappings, classification, changes):
    data = json_bytes(value)
    put(name, data)
    mappings[name] = {'original_path':str(source),'original_sha256':sha(raw(source)),
        'public_sha256':sha(data),'bytes':len(data),'conversion':'allowlisted derivative',
        'classification':classification,'changes':changes}

def prepare(mappings):
    OUT.mkdir(parents=True, exist_ok=True)
    require(not OUT.is_symlink(), 'Public output root symlink denied')
    ci = load(OUT / 'ci-exact-source.json')
    require(ci['headRefOid'] == HEAD and len(ci['statusCheckRollup']) == 22 and
        all(c['status'] == 'COMPLETED' and c['conclusion'] == 'SUCCESS' for c in ci['statusCheckRollup']), 'Actual exact-source22 CI successes required')
    # Root wrote this raw pre-merge gh JSON. Preserve its OPEN state and exact bytes.
    mapping_copy('ci-exact-source.json', OUT / 'ci-exact-source.json', mappings, 'raw pre-merge public CI status JSON;22 successes;not merge receipt')
    if (OUT / 'observed-layer-build.json').exists():
        mapping_copy('observed-layer-build.json',OUT / 'observed-layer-build.json',mappings,'root structured actual build-stage transcription;not raw terminal byte identity')
    require(sha(raw(CONTEXT / 'expected-ui-runtime.json')) == DESCRIPTOR, 'Prepared descriptor changed')
    expected = load(CONTEXT / 'expected-ui-runtime.json')
    require(expected['final_head'] == HEAD and expected['final_tree'] == TREE and expected['portal_head'] == PORTAL,
            'Actual source/tree/retained portal pins required')
    readiness = load(HELPERS / 'readiness.json')
    for name, wanted in readiness['files'].items():
        require(sha(raw(HELPERS / name)) == wanted, 'Reviewed helper changed: ' + name)
        mapping_copy('helpers/' + name, HELPERS / name, mappings)
    mapping_copy('helpers/readiness.json', HELPERS / 'readiness.json', mappings)
    for name in ['Dockerfile','.dockerignore','expected-ui-runtime.json','browser-build-provenance.json','preparation-receipt.json','verify_ui_layer.py']:
        mapping_copy('build/' + name, CONTEXT / name, mappings)
    for name in ['prepare_ui_successor.py','build-only-c44d416fcf1a.ps1','build-only-c44d416fcf1a.fly.toml','README.txt']:
        mapping_copy('build/helpers/' + name, BUILD / name, mappings)
    for name in ['source-manifest.json','portal-source-manifest.json']:
        mapping_copy('source/' + name, CONTEXT / 'application' / name, mappings)
    for name in ['frontend/src/avatar/useSaviaVoice.ts','frontend/src/avatar/native-voice.test.tsx',
                 'frontend/server/conversation.py','frontend/server/voice.py','deploy/rc/run.py']:
        require(sha(raw(CONTEXT / 'application' / name)) == expected['new_sources'][name], 'Source artifact changed')
        mapping_copy('source/' + name, CONTEXT / 'application' / name, mappings)
    if EXTERNAL.exists():
        external = load(EXTERNAL)
        require(len(external) == 2 and all(v['status'] == 200 and v['scope'] == 'HEAD only; no body read or film playback'
            and '?' not in v['url'] and 'final_url' not in v for v in external), 'HEAD-only external receipt admission differs')
        mapping_copy('portal-external-destinations-634aa524.json', EXTERNAL, mappings,
                     'exact existing HEAD-only public-destination receipt;no film playback acceptance')
    sibling = EXTERNAL.parent
    portal_receipt = sibling / 'portal-successor-c44d416f-verification.json'
    if portal_receipt.exists():
        portal = load(portal_receipt)
        require(portal['portal_source'] == PORTAL and portal['runtime_source'] == HEAD and portal['image'] == IMAGE
            and portal['runtime_metadata_scope'] == 'supplied from coordinator release receipt; this harness verifies public portal bytes and ingress, not runtime source',
            'Independent public portal supplied metadata scope changed')
        mapping_copy('portal-successor-c44d416f-verification.json',portal_receipt,mappings,'exact independent public portal verification;runtime metadata is supplied,not independently measured by this harness')
        mapping_copy('portal-successor-harness.py',sibling/'verify-portal-successor.py',mappings)
    summary = {'schema':'savia-ack-successor-observed-build/v1','application_source':HEAD,'git_tree':TREE,'image':IMAGE,
        'evidence_type':'Root reported actual successful tool observations;not raw terminal byte identity',
        'raw_terminal_build_log_recorded':False,'observed_stages':[
            {'phase':'before','source_files':183,'browser_files':22,'native_files':4,'portal_files':28,'passed':True},
            {'phase':'remove-ui','removed_old_browser_files':22,'remaining_browser_files':0,'passed':True},
            {'phase':'after','source_files':183,'fresh_browser_files':21,'native_files':4,'portal_files':28,'passed':True}],
        'scope':'Immutable image build and guard observations reported by root;runtime and native acceptance require actual separate receipts.'}
    put('build-observed-summary.json',json_bytes(summary))
    return expected

def actual_runtime(expected, mappings):
    runtime = load(CONTEXT / 'runtime-verification.json')
    require(runtime['schema'] == 'savia-ack-successor-runtime/v1' and runtime['application_source'] == HEAD
        and runtime['git_tree'] == TREE and runtime['image'] == IMAGE and runtime['portal_source'] == PORTAL
        and runtime['expected_descriptor_sha256'] == DESCRIPTOR, 'Actual runtime pin mismatch')
    require(runtime['source_hashes'] == expected['new_sources'] and runtime['served_ui'] == expected['new_browser']
        and runtime['retained_runtime_hashes'] == expected['native'] and runtime['portal_hashes'] == expected['portal']
        and runtime['retained_pitch_media_hashes'] == expected['retained_pitch_media']
        and runtime['fresh_browser_verified'] is True and runtime['preserved_native_runtime'] is True
        and runtime['preserved_machine_configuration'] is True, 'Actual full component proof differs')
    public = load(CONTEXT / 'public-assets-verification.json')
    require(public['application_source'] == HEAD and public['image'] == IMAGE and public['portal_source'] == PORTAL
        and public['verified_public_assets'] == 27 and public['health'] == 200 and public['entry_gateway'] == 200
        and public['anonymous_api'] == 401 and public['internal_manifest'] == 404, 'Actual public guards missing')
    card = load(CONTEXT / 'card-status-continuity.json')
    require(card['application_source'] == HEAD and card['image'] == IMAGE and card['portal_source'] == PORTAL
        and card['passed'] is True and card['http_checks'] == 12 and card['provider_calls'] == 0
        and card['new_card_prepare_confirm_cancel_requests'] == 0 and len(card['cases']) == 2, 'Actual read-only card proof missing')
    promotion = load(CONTEXT / 'promotion-verification.json')
    require(promotion['application_source'] == HEAD and promotion['image'] == IMAGE and promotion['configuration_preserved'] is True
        and promotion['accepted_private_snapshot_sha256'] == runtime['accepted_private_snapshot_sha256'], 'Actual promotion/config continuity differs')
    for name in ['promotion-verification.json','runtime-verification.json','public-assets-verification.json','card-status-continuity.json']:
        mapping_copy(name,CONTEXT / name,mappings,'actual sanitized public proof;no private config/binding fields')
    return runtime, card

def native_derivative(private_root, expected, runtime, card, mappings, continuation=False):
    private_root = Path(private_root).resolve()
    base = PT_PRIVATE_BASE if continuation else PRIVATE_BASE
    helpers = PT_HELPERS if continuation else HELPERS
    language = 'pt' if continuation else 'es'
    require(base.resolve() in private_root.parents and private_root.is_dir() and not private_root.is_symlink(),
            'Actual native evidence must be a fresh successor private capture child')
    source = private_root / 'receipt-private.json'
    receipt = load(source)
    require(receipt['passed'] is continuation and receipt['preparedOnly'] is False
        and receipt['executionStayedWithinRequestBudget'] is True and receipt['durationMs'] <= 120000
        and receipt['observedProviderEligibleResultRequests'] == 1 and receipt['observedNegativeResultRequests'] == 1
        and receipt['actualUIPlayedAcks'] == 1, 'Actual bounded1-turn native attempt receipt required')
    if continuation:
        require(receipt['failure'] is None and receipt['runtime']['prior_es_attempt_sha256'] == PARTIAL_SHA, 'Successful PT continuation must anchor prior ES attempt')
    else:
        require(sha(raw(source)) == PARTIAL_SHA and 'waitForResponse' in receipt['failure'], 'Exact preserved failed initial attempt required')
    require(receipt['runtime']['git_head'] == HEAD and receipt['runtime']['image_digest'] == IMAGE.split('@')[1]
        and receipt['runtime']['browser_source'] == HEAD and receipt['runtime']['portal_source'] == PORTAL
        and receipt['runtime']['expected_ui_runtime_sha256'] == DESCRIPTOR
        and receipt['runtime']['source_manifest_sha256'] == expected['final_source_manifest_sha256'], 'Actual native runtime binding differs')
    require(receipt['harnessSha256'] == sha(raw(helpers / 'native_live.mjs')), 'Actual native harness changed')
    require([(c['language'],c['fictionalProfile']) for c in receipt['cases']] == [(language,'colombia' if continuation else 'mexico')], 'Actual one approved case required')
    cases = []
    for case in receipt['cases']:
        language = case['language']; playback = case['uiGuidancePlayback']; ack = playback['actualUIAck']
        require(case['passed'] is True and playback['strictHostCaptionEquality'] is True and playback['caveatPresentInCaption'] is True
            and playback['transportProtocolAccepted'] is True and playback['actualUIResultInputEqualToHostReply'] is True
            and playback['sampleRate'] == 24000 and ack['httpStatus'] == 200 and ack['complete'] is True
            and ack['exactSamples'] is True and ack['emittedByProductUI'] is True and ack['noHarnessAckInjection'] is True
            and ack['afterStreamCompletion'] is True and ack['playedSamples'] == playback['samples'], 'Actual exact product UI playback receipt missing')
        require(case['existingCardProtection']['savedReceiptUnchanged'] is True
            and case['existingCardProtection']['newPrepareConfirmCancelRequests'] == 0
            and case['negativeTamperedResult']['httpStatus'] == 409 and case['negativeTamperedResult']['providerEligible'] is False,
            'Read-only card/tampered result guards missing')
        for asset in case['servedAssets']:
            require(expected['new_browser'].get(asset['path']) == asset['sha256'], 'Observed native UI asset differs')
        audio_dir = private_root / language / 'audio'
        audio_receipt = load(audio_dir / 'native-audio.json')
        complete = [t for t in audio_receipt['turns'] if t['completed']]
        require(len(complete) == 1 and audio_receipt['requestInjection'] is False and audio_receipt['audioInjection'] is False,
                'One actual passive captured complete native turn required per case')
        turn = complete[0]
        audio_name = turn['audio']
        require(re.fullmatch(r'native-[0-9]{2}\.wav',audio_name) is not None, 'Unexpected capture audio filename')
        wav_file = audio_dir / audio_name; ndjson_file = audio_dir / audio_name.replace('.wav','.ndjson')
        events = [json.loads(line) for line in raw(ndjson_file).decode('utf-8').splitlines() if line.strip()]
        require(events[0]['type'] == 'start' and events[0]['sample_rate'] == 24000 and events[-1]['type'] == 'complete'
            and events[0]['turn_id'] == events[-1]['turn_id'] and not any(e['type'] in ['error','heard','delegate'] for e in events),
            'Exact result-only native start/complete capture required')
        pcm = b''.join(base64.b64decode(e['data'],validate=True) for e in events if e['type'] == 'audio')
        caption = ''.join(e['text'] for e in events if e['type'] == 'caption')
        require(pcm and len(pcm)%2 == 0 and len(pcm)//2 == events[-1]['samples'] == playback['samples'] == ack['playedSamples'], 'Exact captured PCM/ACK sample count differs')
        require(caption == events[-1]['text'] == playback['actualNativeCaption'] == playback['actualHostReply'] == turn['transcript'], 'Exact captured caption differs')
        with wave.open(str(wav_file),'rb') as wav:
            require(wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 24000
                and wav.readframes(wav.getnframes()) == pcm, 'Captured WAV does not preserve exact PCM')
        wav_bytes = raw(wav_file)
        require(len(wav_bytes) == 44 + len(pcm) and wav_bytes[:4] == b'RIFF' and wav_bytes[8:12] == b'WAVE'
            and wav_bytes[12:16] == b'fmt ' and wav_bytes[36:40] == b'data' and wav_bytes[44:] == pcm,
            'Only passive helper fixed44-byte WAV header plus exact PCM is allowed')
        mapping_copy('native/' + language + '.wav',wav_file,mappings,'exact passive actual captured WAV;PCM byte-identical to stream')
        # Endpoint turn IDs are receipt capabilities. Never publish them.
        sanitized = []
        for event in events:
            if event['type'] == 'start': value={'type':'start','sample_rate':event['sample_rate'],'public_turn_label':language+'-observation-01'}
            elif event['type'] == 'caption': value={'type':'caption','text':event['text']}
            elif event['type'] == 'audio': value={'type':'audio','data':event['data']}
            elif event['type'] == 'complete': value={'type':'complete','text':event['text'],'samples':event['samples'],'public_turn_label':language+'-observation-01'}
            else: raise RuntimeError('Unrecognized native event denied in public derivative')
            sanitized.append(value)
        data = ('\n'.join(json.dumps(e,ensure_ascii=False,separators=(',',':')) for e in sanitized)+'\n').encode('utf-8')
        name = 'native/' + language + '.ndjson'
        put(name,data)
        mappings[name]={'original_path':str(ndjson_file),'original_sha256':sha(raw(ndjson_file)),
            'public_sha256':sha(data),'bytes':len(data),'conversion':'capability-redacted derivative',
            'classification':'actual event order/audio base64/caption/sample bytes preserved',
            'changes':['turn_id omitted; non-callable public_turn_label added','JSON reserialized UTF-8 withLF','unknown fields never copied']}
        cases.append({'case_passed':True,'language':language,'fictional_profile':case['fictionalProfile'],'typed_message':case['typedMessage'],
            'actual_host_reply':caption,'actual_native_caption':caption,'caption_sha256':sha(caption.encode('utf-8')),
            'strict_host_caption_equality':True,'no_real_bank_caveat_present':True,'sample_rate':24000,'samples':len(pcm)//2,
            'seconds':len(pcm)//2/24000,'pcm_sha256':sha(pcm),'audio':'native/'+language+'.wav','events':'native/'+language+'.ndjson',
            'actual_ui_playback_ack':{k:ack[k] for k in ['httpStatus','complete','playedSamples','exactSamples','afterStreamCompletion','emittedByProductUI','noHarnessAckInjection','atMs']},
            'existing_card_protection':{k:case['existingCardProtection'][k] for k in ['initialOwnedStatusVerified','state','receiptStatus','simulated','realBankAction','initialSavedReceiptSha256','rereadSavedReceiptSha256','savedReceiptUnchanged','newPrepareConfirmCancelRequests']},
            'observed_served_assets':case['servedAssets'],'tampered_registered_result':{'http_status':409,'provider_eligible':False},
            'physical_microphone_qualified':False,'physical_hearing_qualified':False,'waveform_text_alignment_qualified':False})
    public = {'schema':'savia-voice-ack-live-public-attempt/v1','passed':receipt['passed'],'application_source':HEAD,'git_tree':TREE,
        'browser_source':HEAD,'image':IMAGE,'source_manifest_sha256':expected['final_source_manifest_sha256'],
        'expected_ui_runtime_sha256':DESCRIPTOR,'served_ui':expected['new_browser'],'portal_source':PORTAL,
        'retained_native_server_source':NATIVE,'critical_server_hashes':expected['critical_server_sources'],
        'native_harness_sha256':receipt['harnessSha256'],'capture_helper_sha256':sha(raw(helpers / 'capture_savia_audio.mjs')),
        'started_at':receipt['startedAt'],'finished_at':receipt['finishedAt'],'duration_ms':receipt['durationMs'],
        'new_provider_eligible_result_requests':1,'actual_product_ui_full_playback_acks':1,'provider_ineligible_negative_requests':1,
        'new_card_writes':0,'asr_input_requests':0,'fallback_voice_requests':0,'provider_cost_usd':None,'cases':cases,
        'receipt_source':'Actual passive browser fetch clone plus product UI /api/voice/played request andHTTP200 observations;no ACK injected',
        'scope':('One successful PT-only continuation after preserved successful ES case in failed original batch.' if continuation else
            'Original two-case batch failed in unrecorded auth wait before PT case creation;ES case completed successfully. Timeout may be profiles or login;exact wait is not identifiable from saved receipt.'),
        'failure':receipt['failure'],'original_batch_remains_failed':True,
        'limits':['Live ACK error recovery is not injected;offline148/148 source coverage contains503/network/auth recovery tests.',
            'Exact provider caption matching does not prove waveform/text alignment or physical hearing.',
            'No full film playback, provider dollar-cost, fleet, or broad production acceptance.',
            'Original6219 native proofs remain dated predecessor evidence and are unchanged.'],
        'privacy':{'auth_recording':False,'storage_state_published':False,'private_config_or_binding_published':False,
            'turn_receipt_capabilities_published':False,'screenshots_or_video_published':False}}
    if continuation:
        diagnostics=[]
        for observation in receipt.get('unrecordedAuthObservations',[]):
            if 'path' in observation:
                require(observation['path'] in ['/', '/_rc/enter', '/api/auth/profiles', '/api/auth/login']
                    and observation['method'] in ['GET','POST'] and isinstance(observation['status'],int), 'Unexpected auth diagnostic path denied')
            if 'stage' in observation:
                require(observation['stage'] in ['profiles-response-wait-start','profiles-response-read','login-response-wait-start','login-response-accepted'], 'Unexpected auth stage denied')
            diagnostics.append({k:observation[k] for k in ['profile','language','path','method','status','stage','atMs'] if k in observation})
        public['unrecorded_auth_diagnostics_route_status_timing_only']=diagnostics
        public['prior_es_attempt_sha256']=PARTIAL_SHA
    name = 'attempts/pt-continuation.json' if continuation else 'attempts/es-partial-failed-batch.json'
    derivative(name,public,source,mappings,'allowlisted actual native public attempt receipt',
        ['only bounded public fields copied','no cookies/headers/storage/config/binding/token IDs/errors/screenshots/video paths copied'])
    return public

def privacy(files):
    forbidden_names = [r'\.private\.',r'(^|/)\.env',r'(^|/)(cookies|storage-state|machine-config)\.',r'\.pem$',r'\.key$']
    token = re.compile(rb'Bearer\s+[A-Za-z0-9._~+/-]{20,}|sk-[A-Za-z0-9_-]{20,}|[?&](?:X-Amz-Signature|sig|token|access_token|code)=',re.I)
    findings=[]
    for name in files:
        if any(re.search(p,name,re.I) for p in forbidden_names): findings.append(name+':forbidden filename')
        file=destination(name)
        if file.suffix.lower() not in ['.wav'] and token.search(raw(file)): findings.append(name+':credential or signed URL pattern')
    require(not findings,'Privacy scan rejected public bundle: '+str(findings))
    return {'schema':'savia-voice-ack-public-privacy/v1','passed':True,'allowlisted_file_count':len(files),
        'checks':['explicit public allowlist','no private config/binding/state/cookies copied','no bearer/API key/signed URL patterns',
            'native receipt is field-allowlisted','NDJSON turn capabilities omitted','WAV has only PCM16mono24k audio metadata',
            'no auth screenshots/video/raw browser state copied'],
        'scope':'Local content and allowlist review;independent source audit additionally requested. Raw nonsecret temporary paths retained only for provenance.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','failed-attempt','finalize'])
    parser.add_argument('--native-private-root',type=Path)
    parser.add_argument('--pt-native-private-root',type=Path)
    args=parser.parse_args()
    mappings={}; expected=prepare(mappings)
    if args.mode=='prepare':
        require(args.native_private_root is None,'Preparation cannot claim native execution')
        put('preparation-index.json',json_bytes({'schema':'savia-ack-public-preparation/v1','prepared_only':True,
            'application_source':HEAD,'git_tree':TREE,'expected_image':IMAGE,'files':mappings,
            'runtime_acceptance':'pending actual runtime/public/card/native receipts','provider_calls_performed_by_builder':0}))
        print(json.dumps({'prepared_only':True,'bundle':str(OUT),'files':len(mappings),'network_calls':0,'provider_calls':0}))
        return
    require(args.native_private_root is not None,'Finalization requires actual successful new2-call native capture path')
    runtime,card=actual_runtime(expected,mappings)
    es=native_derivative(args.native_private_root,expected,runtime,card,mappings)
    if args.mode=='failed-attempt':
        print(json.dumps({'failed_original_batch_preserved':True,'qualified_es_cases':1,'new_provider_calls_observed':1,
            'actual_ui_acks_observed':1,'pt_acceptance':'pending','card_writes':0,'builder_provider_calls':0}))
        return
    require(args.pt_native_private_root is not None,'Finalization requires actual PT-only continuation receipt')
    for name,wanted in load(PT_HELPERS/'readiness.json')['files'].items():
        require(sha(raw(PT_HELPERS/name))==wanted,'Reviewed PT continuation helper changed')
        mapping_copy('pt-continuation-helpers/'+name,PT_HELPERS/name,mappings)
    mapping_copy('pt-continuation-helpers/readiness.json',PT_HELPERS/'readiness.json',mappings)
    pt=native_derivative(args.pt_native_private_root,expected,runtime,card,mappings,continuation=True)
    combined={'schema':'savia-voice-ack-live-public/v1','passed':True,'application_source':HEAD,'git_tree':TREE,'image':IMAGE,
        'browser_source':HEAD,'portal_source':PORTAL,'served_ui':expected['new_browser'],'retained_native_server_source':NATIVE,
        'expected_ui_runtime_sha256':DESCRIPTOR,'source_manifest_sha256':expected['final_source_manifest_sha256'],
        'observed_languages':['es','pt'],'observed_language_case_count':2,'new_provider_eligible_result_requests':2,
        'actual_product_ui_full_playback_acks':2,'provider_ineligible_negative_requests':2,'new_card_writes':0,
        'original_two_case_batch_passed':False,'original_failed_attempt_sha256':PARTIAL_SHA,
        'attempts':['attempts/es-partial-failed-batch.json','attempts/pt-continuation.json'],'cases':es['cases']+pt['cases'],
        'scope':'Two observed language cases across preserved failed ES-first batch plus successful PT-only continuation;not a successful original2/2 batch.',
        'limits':es['limits'],'provider_cost_usd':None,'physical_hearing_qualified':False,'waveform_text_alignment_qualified':False}
    put('native-receipt.json',json_bytes(combined))
    approval={'schema':'savia-pt-continuation-root-approval/v1','evidence_type':'Trusted explicit root GO supplied in collaboration;not private binding bytes or raw full conversation identity',
        'approved_source':HEAD,'approved_image':IMAGE,'approved_prior_es_attempt_sha256':PARTIAL_SHA,
        'approved_cases':['pt/colombia'],'maximum_new_provider_eligible_calls':1,'maximum_negative_requests':1,
        'maximum_product_ui_acks':1,'maximum_duration_ms':120000,'new_card_writes_allowed':0,
        'auth_profile_response_timeout_ms':30000,'auth_login_response_timeout_ms':30000,'auth_default_timeout_ms':30000,
        'product_default_timeout_ms':10000,'runtime_proof_max_age_seconds':900,
        'original_es_batch_remains_failed':True,'replay_es_authorized':False,
        'approved_helper_readiness_sha256':sha(raw(PT_HELPERS/'readiness.json')),
        'credential_or_binding_bytes_published':False,'scope':'Fresh one-call PT-only continuation after exact prior ES evidence was reviewed;no automatic retry.'}
    put('continuation-root-approval.json',json_bytes(approval))
    mappings['native-receipt.json']={'conversion':'joined allowlisted derivative','public_sha256':sha(raw(OUT/'native-receipt.json')),
        'original_sources':[{'path':str(Path(args.native_private_root)/'receipt-private.json'),'sha256':PARTIAL_SHA},
            {'path':str(Path(args.pt_native_private_root)/'receipt-private.json'),'sha256':sha(raw(Path(args.pt_native_private_root)/'receipt-private.json'))}],
        'changes':['joins two actual individually qualified language cases','original batch failed status retained','no IDs/credentials/private config/binding copied']}
    mapping_copy('bundle-builder.py',Path(__file__),mappings,'allowlisted local-only public derivative builder;not invoked for any provider work')
    allowed = set(mappings) | {'build-observed-summary.json','preparation-index.json','continuation-root-approval.json'}
    actual = {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()}
    require(actual == allowed,'Unexpected public bundle files denied: '+str(actual.symmetric_difference(allowed)))
    files={p.relative_to(OUT).as_posix():{'sha256':sha(raw(p)),'bytes':p.stat().st_size}
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ['bundle-manifest.json','privacy-review.json']}
    review=privacy(files)
    put('privacy-review.json',json_bytes(review))
    files['privacy-review.json']={'sha256':sha(raw(OUT/'privacy-review.json')),'bytes':(OUT/'privacy-review.json').stat().st_size}
    identity=sha(json.dumps({n:v['sha256'] for n,v in files.items()},sort_keys=True,separators=(',',':')).encode('utf-8'))
    manifest={'schema':'savia-voice-ack-live-public-bundle/v1','application_source':HEAD,'git_tree':TREE,'image':IMAGE,
        'browser_source':HEAD,'portal_source':PORTAL,'retained_native_server_source':NATIVE,'passed':True,
        'bundle_file_map_sha256':identity,'files':files,'original_to_public_mapping':mappings,
        'privacy_review_passed':True,'new_provider_eligible_result_calls':2,'new_card_writes':0,
        'raw_terminal_build_log_identity_claimed':False,'full_film_playback_claimed':False,
        'provider_calls_performed_by_builder':0,'network_calls_performed_by_builder':0,
        'destination_requested_by_root':'docs/submission/measurements/voice-ack-live',
        'scope':'Public derivatives of actual bounded c44 successor evidence;no frozen6219 proof changes.'}
    put('bundle-manifest.json',json_bytes(manifest))
    print(json.dumps({'passed':True,'bundle':str(OUT),'bundle_file_map_sha256':identity,
        'manifest_sha256':sha(raw(OUT/'bundle-manifest.json')),'public_files':len(files)+1,'privacy_review_passed':True,
        'new_actual_native_calls':2,'builder_provider_calls':0,'card_writes':0}))

if __name__=='__main__': main()
