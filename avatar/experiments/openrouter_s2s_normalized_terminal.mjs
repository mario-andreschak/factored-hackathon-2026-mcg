/** Separately admitted application compatibility probe; --plan is inert. */
import { createHash } from 'node:crypto';
import { lstat, readFile, mkdir, writeFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { MODEL, VOICE, CASES, RATE, LIMITS, requestBody, validateFixture, forecastSecond } from './openrouter_s2s_audition.mjs';
import { PRIOR as FIRST_FAILURE, NAMESPACE as SDK_NAMESPACE, plan as sdkPlan, initialForecast as sdkForecast,
  validatePriorEvidence, correctedAudition, saveDiagnosticAudio } from './openrouter_s2s_sdk_terminal.mjs';

const AVATAR = fileURLToPath(new URL('../', import.meta.url));
const ORIGINAL = path.join(AVATAR, '.local', 'openrouter-s2s');
const SDK_CORRECTION = path.join(AVATAR, '.local', 'openrouter-s2s-sdk-terminal');
const DIRECTORY = path.join(AVATAR, '.local', 'openrouter-s2s-normalized-terminal');
const FIXTURES = path.join(AVATAR, '.local', 'qwen-native', '20261001-084853-1790862533806878800');
export const NAMESPACE = 'openrouter_s2s_application_normalized_expiry_v1';
export const PRIOR = Object.freeze({ totalCostUsd: .014038, sdkCorrectionCostUsd: .007344,
  firstReportSha256: FIRST_FAILURE.reportSha256,
  secondReportSha256: 'f8eeb03f7d422127251c2652b0f5d61bcf1791beeb3eeebb0a25547d7b14c8e9',
  secondReport: '2026-10-01T16-07-55-356Z/report.json' });
const sha = value => createHash('sha256').update(value).digest('hex');
const fail = code => { throw Object.assign(new Error(code), { code }); };

export function initialForecast() {
  const old = sdkForecast();
  const total = PRIOR.totalCostUsd + old.inputForecastUsd + old.outputReservationUsd;
  return { ...old, knownPriorCostUsd: PRIOR.totalCostUsd, forecastIncludingPriorUsd: total,
    allowed: total <= LIMITS.estimatedTotalUsdCeiling, hardSpendGuarantee: false };
}

export function plan() {
  return { ...sdkPlan(), status: 'application_correction_prepared_not_dispatched', namespace: NAMESPACE,
    priorFailures: PRIOR, firstRequestForecast: initialForecast(),
    completionMode: 'application-normalized', completionLabel: 'application_normalized_expiry_terminal',
    sdkDefaultChanged: false, normalizationIsExactSdkContract: false,
    normalizationIsApplicationCompatibilityInference: true,
    references: { ...sdkPlan().references,
      streamedAudioFields: 'https://github.com/openai/openai-dotnet/blob/main/README.md',
      accountingMetadata: 'https://openrouter.ai/docs/api/reference/streaming' },
    positiveExpiryShapeRecorded: true, previousFailedReceiptsRemainFailed: true,
    spanishDiagnosticVoiceAcceptedByUser: true, portugueseVoiceQualityVerified: false,
    bodyChanged: false, liveWebsocketQualified: false, bankingAccess: false };
}

export function validateNormalizationEvidence(firstReport, firstAdmission, secondReport, secondAdmission) {
  const first = validatePriorEvidence(firstReport, firstAdmission);
  if (!Buffer.isBuffer(secondReport) || secondReport.length > 32768 || sha(secondReport) !== PRIOR.secondReportSha256)
    fail('second_failure_hash_mismatch');
  if (!Buffer.isBuffer(secondAdmission) || secondAdmission.length > 8192) fail('second_admission_invalid');
  let report, admission;
  try { report = JSON.parse(secondReport); admission = JSON.parse(secondAdmission); } catch { fail('second_evidence_invalid_json'); }
  const sample = report.samples?.[0];
  if (report.namespace !== SDK_NAMESPACE || report.model !== MODEL || report.voice !== VOICE || report.status !== 'failed' ||
      report.upstreamCalls !== 1 || report.samples?.length !== 1 || sample.id !== 'es' || sample.status !== 'failed' ||
      sample.code !== 'incomplete_audio_stream' || sample.strictCompletionPassed !== false ||
      report.correctionCostUsd !== PRIOR.sdkCorrectionCostUsd || report.totalObservedCostIncludingPriorUsd !== PRIOR.totalCostUsd ||
      admission.namespace !== SDK_NAMESPACE || admission.status !== 'spent_before_dispatch' || admission.model !== MODEL ||
      admission.voice !== VOICE || admission.priorFailure?.reportSha256 !== first.reportSha256)
    fail('second_failure_provenance_mismatch');
  return { firstReportSha256: first.reportSha256, firstAdmissionSha256: first.oldAdmissionSha256,
    secondReportSha256: sha(secondReport), secondAdmissionSha256: sha(secondAdmission), knownPriorCostUsd: PRIOR.totalCostUsd };
}

export async function consumeNormalizationAdmission(directory, proof) {
  if (proof?.firstReportSha256 !== PRIOR.firstReportSha256 || proof.secondReportSha256 !== PRIOR.secondReportSha256 ||
      proof.knownPriorCostUsd !== PRIOR.totalCostUsd ||
      !/^[a-f0-9]{64}$/.test(proof.firstAdmissionSha256 ?? '') || !/^[a-f0-9]{64}$/.test(proof.secondAdmissionSha256 ?? ''))
    fail('prior_failure_proof_missing');
  await mkdir(directory, { recursive: true });
  const record = { status: 'spent_before_dispatch', namespace: NAMESPACE, priorFailures: proof,
    model: MODEL, voice: VOICE, calls: LIMITS.calls, outputTokens: LIMITS.outputTokens,
    completionMode: 'application-normalized', forecast: initialForecast() };
  await writeFile(path.join(directory, 'application-terminal-admitted.json'), JSON.stringify(record, null, 2) + '\n',
    { flag: 'wx', mode: 0o600 });
  return record;
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1 || args.length && !['--plan', '--execute-normalized-terminal-fix'].includes(args[0])) fail('invalid_arguments');
  if (args[0] !== '--execute-normalized-terminal-fix') { console.log(JSON.stringify(plan())); return; }
  const proof = validateNormalizationEvidence(await readFile(path.join(ORIGINAL, FIRST_FAILURE.report)),
    await readFile(path.join(ORIGINAL, 'native-pcm16-admitted.json')), await readFile(path.join(SDK_CORRECTION, PRIOR.secondReport)),
    await readFile(path.join(SDK_CORRECTION, 'sdk-terminal-correction-admitted.json')));
  const inputs = new Map();
  for (const sample of CASES) {
    const file = path.join(FIXTURES, sample.id + '.wav'), info = await lstat(file);
    if (!info.isFile() || info.isSymbolicLink() || info.size !== sample.bytes) fail('fixture_missing');
    const wav = await readFile(file); validateFixture(wav, sample); requestBody(sample, wav); inputs.set(sample.id, wav);
  }
  if (!initialForecast().allowed) fail('first_cost_forecast_insufficient');
  await consumeNormalizationAdmission(DIRECTORY, proof);
  const destination = path.join(DIRECTORY, new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(destination, { recursive: false });
  const report = { ...plan(), status: 'started', upstreamCalls: 0, knownPriorCostUsd: PRIOR.totalCostUsd,
    correctionCostUsd: 0, totalObservedCostIncludingPriorUsd: PRIOR.totalCostUsd, samples: [] };
  const save = () => writeFile(path.join(destination, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  await save();
  try {
    const key = parseEnv(await readFile(path.join(AVATAR, 'openrouter.env'), 'utf8')).OPENROUTER_API_KEY;
    if (!key?.trim()) fail('local_key_unconfigured');
    for (const sample of CASES) {
      if (report.upstreamCalls >= LIMITS.calls) break;
      if (sample.id === 'pt') {
        const first = report.samples[0]?.usage;
        report.secondRequestForecast = forecastSecond(first && { ...first, costUsd: first.costUsd + PRIOR.totalCostUsd });
        if (!report.secondRequestForecast.allowed) { report.code = report.secondRequestForecast.code; break; }
      }
      report.upstreamCalls++; await save();
      const result = await correctedAudition(fetch, key, sample, inputs.get(sample.id), { terminalMode: 'application-normalized' });
      const files = await saveDiagnosticAudio(destination, sample, result);
      const { rawPcm, wav, ...details } = result;
      if (Number.isFinite(result.usage?.costUsd) && report.correctionCostUsd !== null) report.correctionCostUsd += result.usage.costUsd;
      else report.correctionCostUsd = null;
      report.totalObservedCostIncludingPriorUsd = report.correctionCostUsd === null ? null : report.correctionCostUsd + PRIOR.totalCostUsd;
      report.samples.push({ id: sample.id, locale: sample.locale, inputSha256: sample.sha256, ...details, ...files });
      await save(); if (result.status !== 'completed') break;
    }
    report.status = report.samples.length === CASES.length && report.samples.every(sample => sample.strictCompletionPassed) &&
      report.totalObservedCostIncludingPriorUsd !== null && report.totalObservedCostIncludingPriorUsd <= LIMITS.estimatedTotalUsdCeiling ? 'completed' : 'failed';
  } catch (error) { report.status = 'failed'; report.code = error.code === 'local_key_unconfigured' ? error.code : 'local_preparation_failed'; }
  await save();
  console.log(JSON.stringify({ status: report.status, namespace: NAMESPACE, upstreamCalls: report.upstreamCalls,
    totalObservedCostIncludingPriorUsd: report.totalObservedCostIncludingPriorUsd, outputDirectory: destination,
    samples: report.samples.map(({ id, status, code, completionSource, strictCompletionPassed, previewFile }) =>
      ({ id, status, code, completionSource, strictCompletionPassed, previewFile })),
    normalizationIsApplicationCompatibilityInference: true, liveWebsocketQualified: false, pcmPackagingRateQualified: false }));
  if (report.status !== 'completed') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url)
  main().catch(error => { console.log(JSON.stringify({ status: 'failed', code: ['invalid_arguments', 'prior_failure_hash_mismatch',
    'prior_admission_invalid', 'prior_evidence_invalid_json', 'prior_failure_provenance_mismatch', 'second_failure_hash_mismatch',
    'second_admission_invalid', 'second_evidence_invalid_json', 'second_failure_provenance_mismatch', 'fixture_missing',
    'fixture_hash_mismatch', 'fixture_profile_mismatch', 'prior_failure_proof_missing', 'first_cost_forecast_insufficient'].includes(error.code) ? error.code :
    error.code === 'EEXIST' ? 'normalization_admission_already_spent' : 'local_preparation_failed' })); process.exitCode = 1; });
