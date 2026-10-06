/** Offline only: file reads are mocked; no browser or network is started. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import test from 'node:test';
import {validateBinding,CONTEXT,HEAD,PORTAL_HEAD,DESCRIPTOR_SHA,sha} from './binding_gate.mjs';

const read=fs.readFile.bind(fs);
const priorPath='C:/Users/Moe/.codex/tmp/savia-ack-successor-native-private-c44d416fcf1a/2026-10-06T01-48-18-527Z/receipt-private.json';
const priorBytes=await read(priorPath);
const priorSha='67c436c315c0bb729ff5c68bc3d6919cea9eb5c5076d5a410f044e4960bd5c9e';
const descriptorBytes=await read(path.join(CONTEXT,'expected-ui-runtime.json'));
const expected=JSON.parse(descriptorBytes);
const gateBytes=await read(new URL('./binding_gate.mjs',import.meta.url));

async function fixture(mutate) {
  const proof={schema:'savia-ack-successor-runtime/v1',application_source:HEAD,git_tree:expected.final_tree,
    manifest:{git_tree:expected.final_tree},portal_source:PORTAL_HEAD,
    image:'registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c',expected_descriptor_sha256:DESCRIPTOR_SHA,
    source_manifest_sha256:expected.final_source_manifest_sha256,source_hashes:expected.new_sources,
    served_ui:expected.new_browser,retained_runtime_hashes:expected.native,portal_hashes:expected.portal,
    retained_pitch_media_hashes:expected.retained_pitch_media,fresh_browser_verified:true,
    preserved_native_runtime:true,preserved_machine_configuration:true,machine_state:'started',
    reverified_at_utc:new Date().toISOString()};
  const publicProof={schema:'savia-ack-successor-public-assets/v1',application_source:HEAD,portal_source:PORTAL_HEAD,
    image:proof.image,expected_descriptor_sha256:DESCRIPTOR_SHA,verified_public_assets:27,health:200,
    entry_gateway:200,anonymous_api:401,internal_manifest:404};
  const cfg={schema:'savia-ack-pt-continuation-native-binding/v1',root_go:true,frozen_cohort_complete:true,
    generated_only:true,frozen_healthy:true,native_result_mode:'native_exact',
    authorization:{approved_source_revision:HEAD,approved_prior_es_attempt_sha256:priorSha,approved_image_digest:'sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c'},
    runtime:{git_head:HEAD,git_tree:expected.final_tree,image_digest:'sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c',served_ui:expected.new_browser,
      browser_source:HEAD,portal_source:PORTAL_HEAD,source_manifest_sha256:expected.final_source_manifest_sha256,
      reverified_at_utc:proof.reverified_at_utc},base_url:'https://savia-rc-2026.fly.dev',
    cases:[{language:'pt',profile:'colombia'}],
    prior_es_attempt_path:priorPath,prior_es_attempt_sha256:priorSha,
    expected_ui_runtime_path:path.join(CONTEXT,'expected-ui-runtime.json'),expected_ui_runtime_sha256:DESCRIPTOR_SHA,
    runtime_proof_path:path.join(CONTEXT,'runtime-verification.json'),
    public_assets_proof_path:path.join(CONTEXT,'public-assets-verification.json'),binding_gate_sha256:sha(gateBytes)};
  mutate?.(cfg,proof);
  const proofBytes=Buffer.from(JSON.stringify(proof)), publicBytes=Buffer.from(JSON.stringify(publicProof));
  cfg.runtime_proof_sha256=sha(proofBytes); cfg.public_assets_proof_sha256=sha(publicBytes);
  const bindingPath=path.resolve('offline-no-live-binding.private.json');
  const files=new Map([[bindingPath,Buffer.from(JSON.stringify(cfg))],
    [path.resolve(priorPath),priorBytes],[path.resolve(cfg.expected_ui_runtime_path),descriptorBytes],[path.resolve(cfg.runtime_proof_path),proofBytes],
    [path.resolve(cfg.public_assets_proof_path),publicBytes],[path.resolve(new URL('./binding_gate.mjs',import.meta.url).pathname.slice(1)),gateBytes]]);
  fs.readFile=async(file,encoding)=>{
    const key=file instanceof URL?path.resolve(decodeURIComponent(file.pathname).slice(1)):path.resolve(file);
    assert(files.has(key),'Unexpected file read in offline gate test: '+key);
    const bytes=files.get(key); return encoding?bytes.toString(encoding):bytes;
  };
  try {return await validateBinding(bindingPath);} finally {fs.readFile=read;}
}

test('fresh c44 source/UI/native/portal proof admits exact offline binding',async()=>{
  assert.equal((await fixture()).cfg.runtime.git_head,HEAD);
});
test('old retained22 browser map is rejected before runtime execution',async()=>{
  await assert.rejects(fixture(cfg=>{cfg.runtime.served_ui=expected.old_browser;}));
});
test('stale runtime proof is rejected',async()=>{
  await assert.rejects(fixture((cfg,proof)=>{proof.reverified_at_utc=new Date(Date.now()-901000).toISOString();
    cfg.runtime.reverified_at_utc=proof.reverified_at_utc;}),/Fresh runtime proof/);
});
test('root GO is required',async()=>{
  await assert.rejects(fixture(cfg=>{cfg.root_go=false;}));
});
test('altered gate fingerprint is rejected',async()=>{
  await assert.rejects(fixture(cfg=>{cfg.binding_gate_sha256='0'.repeat(64);}));
});

test('ES replay is rejected',async()=>{await assert.rejects(fixture(cfg=>{cfg.cases.push({language:'es',profile:'mexico'});}));});
test('prior ES receipt SHA must be exact',async()=>{await assert.rejects(fixture(cfg=>{cfg.prior_es_attempt_sha256='0'.repeat(64);}));});
