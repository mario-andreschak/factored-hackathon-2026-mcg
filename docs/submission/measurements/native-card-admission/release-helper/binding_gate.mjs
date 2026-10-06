/** Local exact source/image/UI/config proof gate. Importing issues no request. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
export const ROOT='[private-local-path]';
export const BASE_HEAD='c44d416fcf1ab95bcb16c77651418e6570d79782';
export const PORTAL_HEAD='634aa5244374b3e105ef7864fa100530bab45ec2';
export const BASE_IMAGE='registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c';
export const sha=data=>createHash('sha256').update(data).digest('hex');
export function privateChild(file){
  const full=path.resolve(file),relative=path.relative(path.resolve(ROOT),full);
  assert(relative&&!relative.startsWith('..')&&!path.isAbsolute(relative),'Private helper child required');
  return full;
}
export function descriptorGate(e){
  assert.equal(e.schema,'savia-card-admission-source-guards/v1');assert.equal(e.base_image,BASE_IMAGE);
  assert.equal(e.accepted_head,BASE_HEAD);assert.equal(e.accepted_tree,'fabf02d622f51302e229137405e3607356d00ab0');
  assert.equal(e.accepted_source_manifest_sha256,'6ad47268b2d09dac11fdb74b9f73bff436b8aeed16ae183b15cf824f3828f806');
  assert.match(e.final_head,/^[a-f0-9]{40}$/);assert.notEqual(e.final_head,BASE_HEAD);assert.match(e.final_tree,/^[a-f0-9]{40}$/);
  assert.deepEqual(Object.keys(e.old_sources).sort(),Object.keys(e.new_sources).sort());
  assert.equal(Object.keys(e.new_sources).length,183);
  assert.equal(e.final_head,'f2fa597a481a87b5301531cf180f8f61d1f3ba70');assert.equal(e.final_tree,'1638e0be90b1046bbada1972b6ace1ee62a8e4fa');
  assert.deepEqual(Object.keys(e.old_sources).filter(p=>e.old_sources[p]!==e.new_sources[p]).sort(),['frontend/server/conversation.py','resources/dispute_workflow.flow.json']);
  assert.equal(e.new_sources['frontend/server/conversation.py'],'c978b41c6e2c9078a4659c9104a6fa60587a277417b1b926ff5ecc9d7813ec6d');assert.equal(e.new_sources['resources/dispute_workflow.flow.json'],'43fd857863961f4d87d62b85c9a25ae261b59aa2e74d14c8b3e7cf8406a41d03');
  assert.equal(Object.keys(e.new_browser).length,21);assert.deepEqual(e.old_browser,e.new_browser);
  assert.deepEqual(Object.keys(e.native).sort(),['/opt/runtime-ops/start.mjs','/opt/runtime-ops/controller.mjs','/app/package-lock.json','/app/.next/BUILD_ID'].sort());
  assert.equal(Object.keys(e.portal).length,28);assert.equal(Object.keys(e.retained_pitch_media).length,16);
  assert.equal(e.portal_head,PORTAL_HEAD);assert.equal(e.browser_component.source,BASE_HEAD);
  assert.equal(e.browser_component.git_tree,'fabf02d622f51302e229137405e3607356d00ab0');assert.equal(e.browser_component.public_files,21);
  assert.equal(e.portal_source_manifest_sha256,'652268ee73698b9f73219da6b2a5482bcfbab4efb02fcee7776f7ab9d16b57b7');
  assert.equal(e.build_provenance_sha256,'666544efb1bf6afa6a4b0f053982fc70be2c776c1123fe237a17c2703bfd061e');
  for(const [p,h] of Object.entries(e.portal)){assert.equal(e.old_sources[p],h);assert.equal(e.new_sources[p],h);}
  for(const [p,h] of Object.entries(e.retained_pitch_media))assert.equal(e.portal[p],h);
  return e;
}
export async function validateBinding(bindingPath){
  const cfg=JSON.parse(await fs.readFile(privateChild(bindingPath),'utf8'));
  assert.equal(cfg.schema,'savia-card-admission-native-message-binding/v1');
  for(const key of ['root_go','frozen_cohort_complete','generated_only','frozen_healthy'])assert.equal(cfg[key],true);
  assert.equal(cfg.native_result_mode,'native_exact');assert.equal(cfg.base_url,'https://savia-rc-2026.fly.dev');
  assert.deepEqual(cfg.cases,[{language:'es',profile:'mexico'},{language:'pt',profile:'colombia'}]);
  const descriptorPath=privateChild(cfg.expected_runtime_path),build=path.dirname(descriptorPath);
  assert.equal(path.basename(descriptorPath),'expected-server-runtime.json');
  const bytes=await fs.readFile(descriptorPath);assert.equal(sha(bytes),cfg.expected_runtime_sha256);
  const expected=descriptorGate(JSON.parse(bytes));
  assert.equal(cfg.authorization.approved_source_revision,expected.final_head);
  assert.match(cfg.authorization.approved_image_digest,/^sha256:[a-f0-9]{64}$/);
  assert.notEqual('registry.fly.io/savia-rc-2026@'+cfg.authorization.approved_image_digest,BASE_IMAGE);
  assert.equal(cfg.runtime.git_head,expected.final_head);assert.equal(cfg.runtime.git_tree,expected.final_tree);
  assert.equal(cfg.runtime.image_digest,cfg.authorization.approved_image_digest);
  assert.equal(cfg.runtime.source_manifest_sha256,expected.final_source_manifest_sha256);
  assert.equal(cfg.runtime.browser_source,BASE_HEAD);assert.equal(cfg.runtime.portal_source,PORTAL_HEAD);
  assert.deepEqual(cfg.runtime.served_ui,expected.new_browser);
  assert.equal(path.resolve(cfg.runtime_proof_path),path.join(build,'runtime-verification.json'));
  const proofBytes=await fs.readFile(cfg.runtime_proof_path);assert.equal(sha(proofBytes),cfg.runtime_proof_sha256);
  const proof=JSON.parse(proofBytes);
  assert.equal(proof.schema,'savia-card-admission-runtime/v1');assert.equal(proof.application_source,expected.final_head);
  assert.equal(proof.git_tree,expected.final_tree);assert.equal(proof.browser_source,BASE_HEAD);assert.equal(proof.portal_source,PORTAL_HEAD);
  assert.equal(proof.image,'registry.fly.io/savia-rc-2026@'+cfg.authorization.approved_image_digest);
  assert.equal(proof.expected_descriptor_sha256,cfg.expected_runtime_sha256);
  assert.equal(proof.source_manifest_sha256,expected.final_source_manifest_sha256);
  assert.deepEqual(proof.source_hashes,expected.new_sources);assert.deepEqual(proof.served_ui,expected.new_browser);
  assert.deepEqual(proof.retained_runtime_hashes,expected.native);assert.deepEqual(proof.portal_hashes,expected.portal);
  assert.deepEqual(proof.retained_pitch_media_hashes,expected.retained_pitch_media);
  assert.equal(proof.retained_browser_verified,true);assert.equal(proof.preserved_native_runtime,true);
  assert.equal(proof.preserved_machine_configuration,true);assert.equal(proof.machine_state,'started');
  assert.equal(cfg.runtime.reverified_at_utc,proof.reverified_at_utc);
  assert.equal(path.resolve(cfg.public_assets_proof_path),path.join(build,'public-assets-verification.json'));
  const publicBytes=await fs.readFile(cfg.public_assets_proof_path);assert.equal(sha(publicBytes),cfg.public_assets_proof_sha256);
  const pub=JSON.parse(publicBytes);assert.equal(pub.schema,'savia-card-admission-public-assets/v1');
  assert.equal(pub.application_source,expected.final_head);assert.equal(pub.browser_source,BASE_HEAD);
  assert.equal(pub.portal_source,PORTAL_HEAD);assert.equal(pub.image,proof.image);assert.equal(pub.expected_descriptor_sha256,cfg.expected_runtime_sha256);
  assert.equal(pub.verified_public_assets,27);assert.equal(pub.health,200);assert.equal(pub.entry_gateway,200);assert.equal(pub.anonymous_api,401);assert.equal(pub.internal_manifest,404);
  const at=Date.parse(proof.reverified_at_utc);assert(Number.isFinite(at)&&at<=Date.now()+30000&&Date.now()-at<=900000,'Fresh runtime proof within 15 minutes required');
  assert.equal(sha(await fs.readFile(new URL(import.meta.url))),cfg.binding_gate_sha256);
  assert.equal(sha(await fs.readFile(new URL('./event_gate.mjs',import.meta.url))),cfg.event_gate_sha256);
  return {cfg,expected,proof};
}
