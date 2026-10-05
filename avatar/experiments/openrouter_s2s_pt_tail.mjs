/** One separately admitted Portuguese diagnostic; default --plan is inert. */
import { createHash } from 'node:crypto';
import { lstat, readFile, mkdir, writeFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { MODEL, VOICE, CASES, LIMITS, validateFixture, forecastSecond } from './openrouter_s2s_audition.mjs';
import { PRIOR as FIRST, correctedAudition, saveDiagnosticAudio } from './openrouter_s2s_sdk_terminal.mjs';
import { PRIOR as SECOND, NAMESPACE as NORMALIZED_NAMESPACE, plan as normalizedPlan,
  validateNormalizationEvidence } from './openrouter_s2s_normalized_terminal.mjs';

const AVATAR = fileURLToPath(new URL('../', import.meta.url));
const LOCAL = path.join(AVATAR, '.local');
const DIRECTORY = path.join(LOCAL, 'openrouter-s2s-pt-tail');
const SAMPLE = CASES[1];
export const NAMESPACE = 'openrouter_s2s_pt_metadata_tail_v1';
export const PRIOR = Object.freeze({ totalCostUsd: .021584, thirdCostUsd: .007546,
  firstReportSha256: FIRST.reportSha256, secondReportSha256: SECOND.secondReportSha256,
  thirdReportSha256: '26164f44277ea0b260f62174d9c1504f1ed6c4954a7e158532a9c7fe49b028ce',
  thirdReport: '2026-10-01T16-29-28-122Z/report.json' });
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = code => { throw Object.assign(new Error(code), { code }); };

export function plan() {
  const forecast = forecastSecond({ costUsd: PRIOR.totalCostUsd, promptTokens: 105, inputAudioTokens: 41,
    outputAudioTokens: 91, totalTokens: 221 });
  return { ...normalizedPlan(), status: 'pt_metadata_tail_prepared_not_dispatched', namespace: NAMESPACE,
    calls: 1, locales: ['pt-BR'], priorFailures: PRIOR, knownPriorCostUsd: PRIOR.totalCostUsd,
    firstRequestForecast: { ...forecast, knownPriorCostUsd: PRIOR.totalCostUsd,
      forecastIncludingPriorUsd: PRIOR.totalCostUsd + forecast.inputForecastUsd + forecast.outputReservationUsd },
    completionMode: 'application-metadata-tail', completionLabel: 'application_normalized_expiry_terminal_with_metadata_tail',
    orderedChoiceShapeLimit: 256, rawEventsStored: false, portugueseVoiceQualityVerified: false,
    spanishCalls: 0, retries: 0, fallback: false, gpuCalls: 0, asrCalls: 0, dedicatedTtsCalls: 0 };
}

export function validateTailEvidence(firstReport, firstAdmission, secondReport, secondAdmission, thirdReport, thirdAdmission) {
  const firstTwo = validateNormalizationEvidence(firstReport, firstAdmission, secondReport, secondAdmission);
  if (!Buffer.isBuffer(thirdReport) || thirdReport.length > 65536 || sha(thirdReport) !== PRIOR.thirdReportSha256)
    fail('third_failure_hash_mismatch');
  if (!Buffer.isBuffer(thirdAdmission) || thirdAdmission.length > 8192) fail('third_admission_invalid');
  let report, admission;
  try { report = JSON.parse(thirdReport); admission = JSON.parse(thirdAdmission); } catch { fail('third_evidence_invalid_json'); }
  const sample = report.samples?.[0];
  if (report.namespace !== NORMALIZED_NAMESPACE || report.model !== MODEL || report.voice !== VOICE || report.status !== 'failed' ||
      report.upstreamCalls !== 1 || report.samples?.length !== 1 || sample.id !== 'es' || sample.status !== 'failed' ||
      sample.code !== 'content_after_audio_terminal' || sample.strictCompletionPassed !== false ||
      report.correctionCostUsd !== PRIOR.thirdCostUsd || report.totalObservedCostIncludingPriorUsd !== PRIOR.totalCostUsd ||
      admission.namespace !== NORMALIZED_NAMESPACE || admission.status !== 'spent_before_dispatch' ||
      admission.model !== MODEL || admission.voice !== VOICE ||
      admission.priorFailures?.firstReportSha256 !== firstTwo.firstReportSha256 ||
      admission.priorFailures?.secondReportSha256 !== firstTwo.secondReportSha256)
    fail('third_failure_provenance_mismatch');
  return { ...firstTwo, thirdReportSha256: sha(thirdReport), thirdAdmissionSha256: sha(thirdAdmission),
    knownPriorCostUsd: PRIOR.totalCostUsd };
}

export async function consumeTailAdmission(directory, proof) {
  if (proof?.firstReportSha256 !== PRIOR.firstReportSha256 || proof.secondReportSha256 !== PRIOR.secondReportSha256 ||
      proof.thirdReportSha256 !== PRIOR.thirdReportSha256 || proof.knownPriorCostUsd !== PRIOR.totalCostUsd ||
      !['firstAdmissionSha256', 'secondAdmissionSha256', 'thirdAdmissionSha256'].every(key => /^[a-f0-9]{64}$/.test(proof[key] ?? '')))
    fail('prior_failure_proof_missing');
  await mkdir(directory, { recursive: true });
  const record = { status: 'spent_before_dispatch', namespace: NAMESPACE, priorFailures: proof,
    model: MODEL, voice: VOICE, calls: 1, locale: 'pt-BR', outputTokens: LIMITS.outputTokens,
    completionMode: 'application-metadata-tail', forecast: plan().firstRequestForecast };
  await writeFile(path.join(directory, 'pt-metadata-tail-admitted.json'), JSON.stringify(record, null, 2) + '\n',
    { flag: 'wx', mode: 0o600 });
  return record;
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1 || args.length && !['--plan', '--execute-pt-metadata-tail'].includes(args[0])) fail('invalid_arguments');
  if (args[0] !== '--execute-pt-metadata-tail') { console.log(JSON.stringify(plan())); return; }
  const originals = path.join(LOCAL, 'openrouter-s2s'), sdk = path.join(LOCAL, 'openrouter-s2s-sdk-terminal'),
    normalized = path.join(LOCAL, 'openrouter-s2s-normalized-terminal');
  const proof = validateTailEvidence(await readFile(path.join(originals, FIRST.report)),
    await readFile(path.join(originals, 'native-pcm16-admitted.json')), await readFile(path.join(sdk, SECOND.secondReport)),
    await readFile(path.join(sdk, 'sdk-terminal-correction-admitted.json')), await readFile(path.join(normalized, PRIOR.thirdReport)),
    await readFile(path.join(normalized, 'application-terminal-admitted.json')));
  const inputFile = path.join(LOCAL, 'qwen-native', '20261001-084853-1790862533806878800', 'pt.wav');
  const info = await lstat(inputFile);
  if (!info.isFile() || info.isSymbolicLink() || info.size !== SAMPLE.bytes) fail('fixture_missing');
  const wav = await readFile(inputFile); validateFixture(wav, SAMPLE);
  if (!plan().firstRequestForecast.allowed) fail('cost_forecast_insufficient');
  await consumeTailAdmission(DIRECTORY, proof);
  const destination = path.join(DIRECTORY, new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(destination, { recursive: false });
  const report = { ...plan(), status: 'started', upstreamCalls: 0, correctionCostUsd: null,
    totalObservedCostIncludingPriorUsd: PRIOR.totalCostUsd, samples: [] };
  const save = () => writeFile(path.join(destination, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  await save();
  try {
    const key = parseEnv(await readFile(path.join(AVATAR, 'openrouter.env'), 'utf8')).OPENROUTER_API_KEY;
    if (!key?.trim()) fail('local_key_unconfigured');
    report.upstreamCalls = 1; await save();
    const result = await correctedAudition(fetch, key, SAMPLE, wav, { terminalMode: 'application-metadata-tail' });
    const files = await saveDiagnosticAudio(destination, SAMPLE, result);
    const { rawPcm, wav: preview, ...details } = result;
    report.correctionCostUsd = Number.isFinite(result.usage?.costUsd) ? result.usage.costUsd : null;
    report.totalObservedCostIncludingPriorUsd = report.correctionCostUsd === null ? null : PRIOR.totalCostUsd + report.correctionCostUsd;
    report.samples.push({ id: 'pt', locale: 'pt-BR', inputSha256: SAMPLE.sha256, ...details, ...files });
    report.status = result.strictCompletionPassed && report.totalObservedCostIncludingPriorUsd !== null &&
      report.totalObservedCostIncludingPriorUsd <= LIMITS.estimatedTotalUsdCeiling ? 'completed' : 'failed';
  } catch (error) { report.status = 'failed'; report.code = error.code === 'local_key_unconfigured' ? error.code : 'local_preparation_failed'; }
  await save();
  console.log(JSON.stringify({ status: report.status, namespace: NAMESPACE, upstreamCalls: report.upstreamCalls,
    totalObservedCostIncludingPriorUsd: report.totalObservedCostIncludingPriorUsd, outputDirectory: destination,
    samples: report.samples.map(({ id, status, code, completionSource, strictCompletionPassed, previewFile }) =>
      ({ id, status, code, completionSource, strictCompletionPassed, previewFile })),
    applicationMetadataTailIsInference: true, liveWebsocketQualified: false, pcmPackagingRateQualified: false }));
  if (report.status !== 'completed') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url)
  main().catch(error => { console.log(JSON.stringify({ status: 'failed', code: ['invalid_arguments', 'prior_failure_hash_mismatch',
    'prior_admission_invalid', 'prior_evidence_invalid_json', 'prior_failure_provenance_mismatch', 'second_failure_hash_mismatch',
    'second_admission_invalid', 'second_evidence_invalid_json', 'second_failure_provenance_mismatch', 'third_failure_hash_mismatch',
    'third_admission_invalid', 'third_evidence_invalid_json', 'third_failure_provenance_mismatch', 'fixture_missing',
    'fixture_hash_mismatch', 'fixture_profile_mismatch', 'prior_failure_proof_missing', 'cost_forecast_insufficient'].includes(error.code) ? error.code :
    error.code === 'EEXIST' ? 'pt_tail_admission_already_spent' : 'local_preparation_failed' })); process.exitCode = 1; });
